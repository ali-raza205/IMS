"""
Copies uploaded pictures and receipts (MEDIA_ROOT) to MEDIA_BACKUP_DIR.

Only new or changed files are copied, and nothing is ever deleted from the backup, so pictures that were
replaced or removed in the app stay recoverable. Run daily by the "IMS media backup" scheduled task
(backup_media.bat, see DEPLOY.md); safe to run by hand.
"""
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def needs_copy(source, target):
    """True when the target is missing or differs from the source in size or modification time."""
    if not target.exists():
        return True
    source_stat, target_stat = source.stat(), target.stat()
    return source_stat.st_size != target_stat.st_size or int(source_stat.st_mtime) != int(target_stat.st_mtime)


class Command(BaseCommand):
    help = 'Copies new and changed pictures and receipts from MEDIA_ROOT to MEDIA_BACKUP_DIR.'

    def add_arguments(self, parser):
        parser.add_argument('--target', help='Backup folder (default: MEDIA_BACKUP_DIR from settings).')

    def handle(self, *args, **options):
        source_root = Path(settings.MEDIA_ROOT)
        target = options['target'] or getattr(settings, 'MEDIA_BACKUP_DIR', None)
        if not target:
            raise CommandError('Set MEDIA_BACKUP_DIR in local_settings.py, e.g. a folder on another disk or machine.')
        target_root = Path(target)
        if not source_root.exists():
            self.stdout.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} Nothing to back up: {source_root} does not exist yet.')
            return
        if target_root.resolve() == source_root.resolve() or source_root.resolve() in target_root.resolve().parents:
            raise CommandError('MEDIA_BACKUP_DIR must be outside MEDIA_ROOT.')

        copied = unchanged = failed = 0
        copied_bytes = 0
        for source in source_root.rglob('*'):
            if not source.is_file():
                continue
            destination = target_root / source.relative_to(source_root)
            try:
                if needs_copy(source, destination):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)  # keeps the modification time for the next comparison
                    copied += 1
                    copied_bytes += source.stat().st_size
                else:
                    unchanged += 1
            except OSError as error:
                failed += 1
                self.stderr.write(f'Could not copy {source}: {error}')

        self.stdout.write(
            f'{time.strftime("%Y-%m-%d %H:%M:%S")} {source_root} -> {target_root}: '
            f'{copied} copied ({copied_bytes / 1024 / 1024:.1f} MB), {unchanged} already backed up, {failed} failed.'
        )
        if failed:
            raise CommandError(f'{failed} file(s) could not be copied.')

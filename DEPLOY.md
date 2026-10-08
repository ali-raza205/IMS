# Deploying IMS

The server runs a git clone of this repository. Push to `main` and the server installs the new
version by itself within a few minutes.

```
your PC ──git push──▶ GitHub (main) ◀──git pull every 5 min── server: IMS\update.bat ──▶ restarts the server
```

## Day to day

```
git add -A
git commit -m "What changed"
git push
```

Within 5 minutes the server pulls, installs requirements, runs migrations and restarts.
Check `IMS\update.log` on the server to see what happened.

- **Never edit files on the server.** The update stops with "git pull failed" if it finds local changes.
  The only server-side files are `IMS\IMS\local_settings.py`, `serve.pid` and `update.log`, which git ignores.
- **Migrations run against the shared database on every update.** Test a migration before pushing it.
- **To update right away**, run `IMS\update.bat` on the server.

## One-time server setup

1. Install [Git for Windows](https://git-scm.com/download/win) on the server.
2. Clone the repository:
   ```
   cd /d D:\API
   git clone https://github.com/ali-raza205/IMS.git Inventory_Management_git
   ```
3. Create `Inventory_Management_git\IMS\IMS\local_settings.py` from `local_settings.example.py`:
   database login, a new `SECRET_KEY`, `ALLOWED_HOSTS = ['192.168.0.64', 'localhost']`,
   `WAITRESS_HOST = '192.168.0.64'`, `WAITRESS_PORT = 8009`, `WAITRESS_THREADS = 4`
   (the values the old `start_server.bat` set as environment variables).
4. Install dependencies: run `IMS\install.bat` (creates `IMS\venv`).
   Without it the scripts use the Python on PATH.
5. Stop the old server, then swap folders so the paths stay the same:
   ```
   cd /d D:\API
   ren Inventory_Management Inventory_Management_old
   ren Inventory_Management_git Inventory_Management
   ```
6. Start the server: run `D:\API\Inventory_Management\IMS\start_server.bat`.
   Keep the window open; it restarts the server after each update.
   To start it at boot, add a shortcut to it in `shell:startup` for the account that logs on to the server.
7. Schedule the automatic update, run as the same Windows account that runs the server:
   ```
   schtasks /create /tn "IMS auto update" /sc minute /mo 5 /tr "\"D:\API\Inventory_Management\IMS\update.bat\""
   ```
   Check it with `schtasks /query /tn "IMS auto update"`. To stop automatic updates:
   `schtasks /delete /tn "IMS auto update" /f`.

If the repository is private, sign in once on the server (`git fetch` in the folder opens the
GitHub login) with an account that can read the repository, so the scheduled task can pull.

## Rolling back

On your PC: `git revert <commit>` and `git push`. The server installs the revert like any other update.

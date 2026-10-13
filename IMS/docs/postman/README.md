# IMS API – Postman collections for the front end

Two collections, one per screen. Each one walks the screen from start to finish: every request explains what the
screen does with it, who may do it, the fields and the errors to expect. The tests in each request check the response
and pass ids on to the next request, so a whole collection runs top to bottom.

| File | Screen |
|---|---|
| `IMS_Transactions.postman_collection.json` | Transactions: receipts, movements and approvals, district use and returns, stock |
| `IMS_Demands.postman_collection.json` | Demands: raise, refer, approve / rationalize, NDMA requests, issue, return requests |
| `IMS_test.postman_environment.json` | Server address, one login per role, password |
| `sample.jpg` | Image used by the picture / receipt upload example |

## Before you run

**Run against a test server only.** The collections create transactions and demands.

1. Import the two collections and the environment into Postman.
2. In the environment, set `base_url` (e.g. `http://127.0.0.1:8009`), one test login per role (`user_dg`,
   `user_warehouse`, `user_district`, `user_ndma`, `user_inspection`) and `password`.
3. Check the collection variables against your test data: `item` / `sub_cat` / `spec` (Boat / Fiberglass / 19 ft),
   `warehouse` (Lahore Warehouse, 1), `warehouse2` (Muzaffargarh Warehouse, 3) and `district` (Lahore district, 2).
4. Run a collection (Postman Runner, or `postman collection run <file> -e IMS_test.postman_environment.json --working-dir .`).

## Roles

| Login | Role | Sees and does |
|---|---|---|
| `user_dg` | DG PDMA (`master`) | Every location. Approves warehouse movements and returns; refers and decides demands; sends stock anywhere directly |
| `user_warehouse` | Storage location user at a **Warehouse** | Own warehouse. Movements wait for DG approval; issues approved demands |
| `user_district` | Storage location user at a **District** | Own district. Uses its stock freely (Dispatch with a purpose); returns stock; decides return requests |
| `user_ndma` | NDMA (`ndma`) | Only NDMA-owned stock and the demand lines requested from NDMA, which only NDMA decides |
| `user_inspection` | Inspection team (`inspection`) | Approves status changes |

`GET /api/auth/me/` gives `role`, `storage_location_id`, `storage_location_name` and `can_approve_demands`; use
them to choose which parts of each screen to show.

## Things every screen needs

- `Authorization: Bearer <access>` from `POST /api/auth/login/` on every call.
- Errors: HTTP 400 `{"field": ["message"]}` next to the field; 403/404 `{"detail": "..."}`.
- Images (`picture`, `receipt`) are uploaded as multipart/form-data and fetched with the token
  (`/api/transactions/<id>/picture/`), then shown as a blob URL.
- Movements in `approval_status` **pending** count for nothing until approved; show a badge.

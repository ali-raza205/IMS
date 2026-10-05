-- user_profile."Sto_location_id" and purchase_order.location_id were repointed to storage_location
-- by hand, but still held locations (area) ids. Replace each with the storage location of that area.
-- Areas with two storage locations use the "... Warehouse" one (Lahore -> 1, Muzaffargarh -> 3).
--
-- Written against the 2 profiles and 9 purchase orders present on 2026-10-05; run once only,
-- since storage location ids and location ids overlap.

BEGIN;

CREATE TEMP TABLE area_to_storage (location_id bigint PRIMARY KEY, st_loc_id bigint NOT NULL) ON COMMIT DROP;
INSERT INTO area_to_storage VALUES
    (1, 42),   -- Attock
    (3, 6),    -- Bahawalpur
    (4, 7),    -- Bhakkar
    (8, 11),   -- Faisalabad
    (18, 1),   -- Lahore -> Lahore Warehouse
    (24, 3);   -- Muzaffargarh -> Muzaffargarh Warehouse

UPDATE user_profile p SET "Sto_location_id" = m.st_loc_id
FROM area_to_storage m WHERE p."Sto_location_id" = m.location_id;

UPDATE purchase_order po SET location_id = m.st_loc_id
FROM area_to_storage m WHERE po.location_id = m.location_id;

ALTER TABLE user_profile VALIDATE CONSTRAINT "user_profile_Sto_location_id_fkey";
ALTER TABLE purchase_order VALIDATE CONSTRAINT purchase_order_location_id_fkey;

COMMIT;

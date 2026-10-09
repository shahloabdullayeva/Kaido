import base64
import json
import time

import requests

from .config import config
from .db import execute, insert, one, rows
from .logs import get
from .security import decrypt, encrypt


class HorizonError(Exception):
    pass


class HorizonClient:
    def __init__(self, user, password, company, base_url=None, timeout=30):
        if not (user and password):
            raise HorizonError("Horizon credentials are incomplete")
        self.user = user
        self.password = password
        self.company = company
        self.base_url = (base_url or config.HORIZON_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.token = None

    def authenticate(self):
        url = f"{self.base_url}/authentication"
        try:
            response = self.session.post(
                url,
                json={"user": self.user, "password": self.password, **({"company": self.company} if self.company else {})},
                timeout=self.timeout,
            )
        except requests.RequestException as err:
            raise HorizonError(f"Could not reach Horizon: {err}") from err
        if response.status_code in (400, 401):
            raise HorizonError(f"Horizon rejected the login ({response.status_code}): {response.text[:300]}")
        if not response.ok:
            raise HorizonError(f"Horizon auth returned {response.status_code}: {response.text[:200]}")
        try:
            token = (response.json() or {}).get("accessToken")
        except ValueError as err:
            raise HorizonError("Horizon auth returned a response that was not JSON") from err
        if not token:
            raise HorizonError("Horizon auth did not return a token")
        self.token = token
        self.session.headers["Authorization"] = f"Bearer {token}"
        return token

    def get(self, path, params=None, attempt=1):
        if not self.token:
            self.authenticate()
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(url, params=params or {}, timeout=self.timeout)
        except requests.RequestException as err:
            raise HorizonError(f"Could not reach Horizon: {err}") from err
        if response.status_code == 401 and attempt == 1:
            self.token = None
            self.session.headers.pop("Authorization", None)
            return self.get(path, params, attempt + 1)
        if response.status_code == 429 and attempt <= 3:
            time.sleep(min(int(response.headers.get("Retry-After", "2")), 10))
            return self.get(path, params, attempt + 1)
        if response.status_code >= 500 and attempt <= 3:
            time.sleep(attempt)
            return self.get(path, params, attempt + 1)
        if not response.ok:
            raise HorizonError(f"Horizon returned {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as err:
            raise HorizonError("Horizon returned a response that was not JSON") from err

    def paginate(self, path, params=None, limit=100, limit_pages=100):
        params = dict(params or {})
        params["$limit"] = limit
        skip = 0
        collected = []
        pages = 0
        while pages < limit_pages:
            params["$skip"] = skip
            payload = self.get(path, params)
            batch = payload.get("data") if isinstance(payload, dict) else payload
            batch = batch or []
            collected.extend(batch)
            if len(batch) < limit:
                break
            skip += limit
            pages += 1
        return collected

    def drivers(self):
        return self.paginate("/drivers")

    def vehicles(self):
        return self.paginate("/vehicles")

    def driver_statuses(self):
        return self.paginate("/latest_driver_statuses")

    def vehicle_statuses(self):
        return self.paginate("/latest_vehicle_statuses")

    def companies(self):
        return self.paginate("/companies")


def get_integration(company_id):
    return one("select * from integrations where company_id = %s and provider = 'horizoneld'", (company_id,))


def client_for(company_id):
    integration = get_integration(company_id)
    if not integration or not integration["credential"]:
        raise HorizonError("Horizon is not connected for this company.")
    creds = json.loads(decrypt(integration["credential"]))
    return HorizonClient(creds["user"], creds["password"], creds["company"]), integration


def _token_claims(token):
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return {}


def find_company(user, password):
    client = HorizonClient(user, password, None)
    claims = _token_claims(client.authenticate())
    for key in ("companyId", "company", "company_id"):
        if isinstance(claims.get(key), str) and claims[key]:
            return claims[key]
    try:
        companies = client.companies()
    except HorizonError as err:
        raise HorizonError(f"Horizon login works, but it did not say which company it belongs to ({err}); pass --company-key with BOOKIT's Company ID.") from err
    if len(companies) == 1:
        return str(companies[0]["_id"])
    listing = ", ".join(f"{c.get('name') or '?'} = {c.get('_id')}" for c in companies) or "none"
    raise HorizonError(f"This login sees {len(companies)} Horizon companies ({listing}); pass --company-key with the right ID.")


def connect(company_id, user, password, company_key=None, user_id=None):
    company_key = company_key or find_company(user, password)
    client = HorizonClient(user, password, company_key)
    client.authenticate()
    blob = encrypt(json.dumps({"user": user, "password": password, "company": company_key}))
    insert(
        """insert into integrations (company_id, provider, credential, status, created_by, updated_at)
           values (%s, 'horizoneld', %s, 'connected', %s, now())
           on conflict (company_id, provider) do update
             set credential = excluded.credential, status = 'connected', last_error = null, updated_at = now()
           returning id""",
        (company_id, blob, user_id),
    )
    return True


def disconnect(company_id):
    execute(
        """update integrations set credential = null, status = 'disconnected', sync_cursor = null, updated_at = now()
           where company_id = %s and provider = 'horizoneld'""",
        (company_id,),
    )


def _driver_name(driver):
    full = " ".join(part for part in [driver.get("firstName"), driver.get("lastName")] if part).strip()
    return full or (driver.get("username") or "").strip() or None


def import_drivers(company_id, client):
    created = 0
    resolved = {}
    for driver in client.drivers():
        external_id = str(driver.get("_id") or "")
        if not external_id:
            continue
        name = _driver_name(driver)
        if not name:
            continue
        link = one(
            "select * from driver_links where company_id = %s and provider = 'horizoneld' and external_id = %s",
            (company_id, external_id),
        )
        driver_id = link["driver_id"] if link else None
        if driver_id is None:
            match = one(
                "select id from drivers where company_id = %s and lower(name) = lower(%s) limit 1",
                (company_id, name),
            )
            if match:
                driver_id = match["id"]
            else:
                row = insert(
                    """insert into drivers (company_id, name, status, is_outside, notes)
                       values (%s, %s, 'active', false, 'From Horizon ELD') returning id""",
                    (company_id, name),
                )
                driver_id = row["id"]
                created += 1
        else:
            execute("update drivers set name = %s, updated_at = now() where id = %s", (name, driver_id))
        execute(
            """insert into driver_links (company_id, driver_id, provider, external_id, external_username, last_seen_at)
               values (%s, %s, 'horizoneld', %s, %s, now())
               on conflict (company_id, provider, external_id) do update
                 set driver_id = excluded.driver_id, external_username = excluded.external_username, last_seen_at = now()""",
            (company_id, driver_id, external_id, driver.get("username")),
        )
        resolved[external_id] = driver_id
    return created, resolved


def link_vehicles(company_id, client):
    created = 0
    resolved = {}
    for vehicle in client.vehicles():
        external_id = str(vehicle.get("_id") or "")
        if not external_id:
            continue
        vin = (vehicle.get("vin") or "").strip() or None
        name = (vehicle.get("name") or "").strip() or None
        existing = one(
            "select * from vehicle_links where company_id = %s and provider = 'horizoneld' and external_id = %s",
            (company_id, external_id),
        )
        truck_id = existing["truck_id"] if existing else None
        if truck_id is None:
            match = None
            if vin:
                match = one(
                    "select id from trucks where company_id = %s and upper(vin) = upper(%s) limit 1",
                    (company_id, vin),
                )
            if not match and name:
                match = one(
                    "select id from trucks where company_id = %s and lower(unit_number) = lower(%s) limit 1",
                    (company_id, name),
                )
            if match:
                truck_id = match["id"]
            elif vin:
                row = insert(
                    """insert into trucks (company_id, unit_number, vin, status, driver_from_name, notes)
                       values (%s, %s, %s, 'active', false, 'From Horizon ELD') returning id""",
                    (company_id, name or external_id, vin),
                )
                truck_id = row["id"]
                created += 1
        execute(
            """insert into vehicle_links (company_id, truck_id, provider, external_id, external_name, external_vin, last_seen_at)
               values (%s, %s, 'horizoneld', %s, %s, %s, now())
               on conflict (company_id, provider, external_id) do update
                 set external_name = excluded.external_name, external_vin = excluded.external_vin,
                     last_seen_at = now(), truck_id = coalesce(vehicle_links.truck_id, excluded.truck_id)""",
            (company_id, truck_id, external_id, name, vin),
        )
        resolved[external_id] = truck_id
    return created, resolved


def _to_int(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def sync_statuses(company_id, client, drivers_by_ext, trucks_by_ext):
    vehicle_status = {}
    for status in client.vehicle_statuses():
        user_ext = str(status.get("userId") or "")
        if user_ext:
            vehicle_status[user_ext] = status
        vehicle_ext = str(status.get("vehicleId") or "")
        truck_id = trucks_by_ext.get(vehicle_ext)
        driver_id = drivers_by_ext.get(user_ext)
        seen = status.get("time")
        if truck_id and seen and status.get("lat") is not None and status.get("lon") is not None:
            execute(
                """update trucks set latitude = %s, longitude = %s, located_at = %s, location_source = 'horizon', location = null,
                     updated_at = now()
                   where id = %s and company_id = %s and (located_at is null or located_at < %s)""",
                (status.get("lat"), status.get("lon"), seen, truck_id, company_id, seen),
            )
        if truck_id and driver_id:
            execute(
                """update trucks t set driver_id = %s, driver_from_name = false, driver_source = 'horizon', updated_at = now()
                   where t.id = %s and t.company_id = %s
                     and not exists (
                       select 1 from trucks o
                       where o.company_id = t.company_id and o.driver_id = %s and o.id <> t.id
                         and o.located_at is not null
                         and (t.located_at is null or o.located_at > t.located_at))""",
                (driver_id, truck_id, company_id, driver_id),
            )
    written = 0
    for status in client.driver_statuses():
        user_ext = str(status.get("userId") or "")
        if not user_ext:
            continue
        position = vehicle_status.get(user_ext, {})
        execute(
            """insert into hos_status (company_id, driver_id, provider, external_user_id, duty_status,
                 break_remaining, drive_remaining, shift_remaining, cycle_remaining,
                 vehicle_external_id, latitude, longitude, odometer, located_at, raw, updated_at)
               values (%s, %s, 'horizoneld', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
               on conflict (company_id, provider, external_user_id) do update
                 set driver_id = excluded.driver_id, duty_status = excluded.duty_status,
                     break_remaining = excluded.break_remaining, drive_remaining = excluded.drive_remaining,
                     shift_remaining = excluded.shift_remaining, cycle_remaining = excluded.cycle_remaining,
                     vehicle_external_id = excluded.vehicle_external_id, latitude = excluded.latitude,
                     longitude = excluded.longitude, odometer = excluded.odometer,
                     located_at = excluded.located_at, raw = excluded.raw, updated_at = now()""",
            (
                company_id, drivers_by_ext.get(user_ext), user_ext, status.get("dutyStatus"),
                status.get("break"), status.get("drive"), status.get("shift"), status.get("cycle"),
                str(position.get("vehicleId") or "") or None, position.get("lat"), position.get("lon"),
                _to_int(position.get("odometer")), position.get("time"),
                json.dumps({"driver": status, "vehicle": position}),
            ),
        )
        written += 1
    return written


def sync_company(company_id):
    run = insert(
        "insert into sync_runs (company_id, provider) values (%s, 'horizoneld') returning *",
        (company_id,),
    )
    counters = {"drivers_created": 0, "vehicles_created": 0, "hos_rows": 0}
    try:
        client, _integration = client_for(company_id)
        client.authenticate()
        counters["drivers_created"], drivers_by_ext = import_drivers(company_id, client)
        counters["vehicles_created"], trucks_by_ext = link_vehicles(company_id, client)
        counters["hos_rows"] = sync_statuses(company_id, client, drivers_by_ext, trucks_by_ext)
        execute(
            """update integrations set status = 'connected', last_sync_at = now(), last_error = null, updated_at = now()
               where company_id = %s and provider = 'horizoneld'""",
            (company_id,),
        )
        execute(
            "update sync_runs set finished_at = now(), status = 'ok', vehicles_seen = %s where id = %s",
            (len(trucks_by_ext), run["id"]),
        )
        counters["status"] = "ok"
        return counters
    except Exception as err:
        message = str(err)[:500]
        get("horizon").warning("Horizon sync failed for company %s: %s", company_id, message,
                               exc_info=not isinstance(err, HorizonError))
        execute(
            """update integrations set status = 'error', last_error = %s, updated_at = now()
               where company_id = %s and provider = 'horizoneld'""",
            (message, company_id),
        )
        execute("update sync_runs set finished_at = now(), status = 'error', error = %s where id = %s",
                (message, run["id"]))
        counters["status"] = "error"
        counters["error"] = message
        return counters


def sync_all():
    results = {}
    targets = rows(
        """select c.id, c.name from companies c
           join integrations i on i.company_id = c.id and i.provider = 'horizoneld'
           where c.status = 'active' and i.credential is not null""",
    )
    for company in targets:
        results[company["name"]] = sync_company(company["id"])
    return results

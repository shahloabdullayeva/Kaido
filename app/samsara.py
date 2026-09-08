import time

import requests

from .config import config

METERS_PER_MILE = 1609.344


class SamsaraError(Exception):
    pass


class SamsaraClient:
    def __init__(self, token, base_url=None, timeout=30):
        if not token:
            raise SamsaraError("No API token configured")
        self.token = token
        self.base_url = (base_url or config.SAMSARA_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })

    def get(self, path, params=None, attempt=1):
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(url, params=params or {}, timeout=self.timeout)
        except requests.RequestException as err:
            raise SamsaraError(f"Could not reach Samsara: {err}") from err
        if response.status_code == 429 and attempt <= 3:
            wait = int(response.headers.get("Retry-After", "2"))
            time.sleep(min(wait, 10))
            return self.get(path, params, attempt + 1)
        if response.status_code == 401:
            raise SamsaraError("Samsara rejected the token (401). Check the token and its scopes.")
        if response.status_code == 403:
            raise SamsaraError("Token lacks the scope for this data (403). Add the read scopes and try again.")
        if response.status_code >= 500 and attempt <= 3:
            time.sleep(attempt)
            return self.get(path, params, attempt + 1)
        if not response.ok:
            raise SamsaraError(f"Samsara returned {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as err:
            raise SamsaraError("Samsara returned a response that was not JSON") from err

    def paginate(self, path, params=None, limit_pages=40):
        params = dict(params or {})
        params.setdefault("limit", 512)
        collected = []
        pages = 0
        while pages < limit_pages:
            payload = self.get(path, params)
            collected.extend(payload.get("data") or [])
            pagination = payload.get("pagination") or {}
            if not pagination.get("hasNextPage"):
                break
            params["after"] = pagination.get("endCursor")
            pages += 1
        return collected

    def whoami(self):
        return self.get("/me")

    def vehicles(self):
        return self.paginate("/fleet/vehicles")

    def vehicle_stats(self, types, chunk=4):
        merged = {}
        for start in range(0, len(types), chunk):
            group = types[start:start + chunk]
            for row in self.paginate("/fleet/vehicles/stats", {"types": ",".join(group)}):
                key = str(row.get("id") or "")
                if not key:
                    continue
                merged.setdefault(key, {}).update(row)
        return list(merged.values())

    def stats_feed(self, types, after=None):
        params = {"types": ",".join(types)}
        if after:
            params["after"] = after
        payload = self.get("/fleet/vehicles/stats/feed", params)
        pagination = payload.get("pagination") or {}
        return payload.get("data") or [], pagination.get("endCursor")

    def defects(self, updated_after=None):
        params = {}
        if updated_after:
            params["updatedAfterTime"] = updated_after
        for path in ("/fleet/defects/stream", "/fleet/defects"):
            try:
                return self.paginate(path, params, limit_pages=5)
            except SamsaraError as err:
                if "404" in str(err):
                    continue
                raise
        return []


def meters_to_miles(meters):
    if meters is None:
        return None
    return int(round(float(meters) / METERS_PER_MILE))


def lamp_summary(lights):
    if not lights:
        return None, "unknown"
    lit = [name for name, key in (
        ("stop", "stopIsOn"), ("warning", "warningIsOn"),
        ("protect", "protectIsOn"), ("emissions", "emissionsIsOn"),
    ) if lights.get(key)]
    if not lit:
        return None, "low"
    if "stop" in lit:
        return "+".join(lit), "high"
    if "warning" in lit or "protect" in lit:
        return "+".join(lit), "medium"
    return "+".join(lit), "low"


def parse_fault_codes(payload):
    if not payload:
        return []
    faults = []
    j1939 = payload.get("j1939") or {}
    lamp, lamp_severity = lamp_summary(j1939.get("checkEngineLights"))
    for code in j1939.get("diagnosticTroubleCodes") or []:
        spn = code.get("spnId")
        fmi = code.get("fmiId")
        description = " / ".join(part for part in [code.get("spnDescription"), code.get("fmiDescription")] if part)
        faults.append({
            "protocol": "j1939",
            "code_key": f"j1939:{spn}:{fmi}",
            "spn": spn,
            "fmi": fmi,
            "dtc_code": None,
            "description": description or f"SPN {spn} FMI {fmi}",
            "lamp": lamp,
            "severity": lamp_severity,
            "occurrence_count": code.get("occurrenceCount"),
            "raw": code,
        })
    obdii = payload.get("obdii") or {}
    mil_on = bool(obdii.get("checkEngineLightIsOn"))
    buckets = (
        ("confirmedDtcs", "high" if mil_on else "medium"),
        ("pendingDtcs", "low"),
        ("permanentDtcs", "medium"),
    )
    for key, severity in buckets:
        for code in obdii.get(key) or []:
            short = code.get("dtcShortCode") or str(code.get("dtcId") or "unknown")
            faults.append({
                "protocol": "obdii",
                "code_key": f"obdii:{key[:-4]}:{short}",
                "spn": None,
                "fmi": None,
                "dtc_code": short,
                "description": code.get("dtcDescription") or short,
                "lamp": "check engine" if mil_on else None,
                "severity": severity,
                "occurrence_count": None,
                "raw": code,
            })
    return faults

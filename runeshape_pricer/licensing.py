"""License gate backed by Keygen (https://keygen.sh).

Flow on startup:
  1. read the stored license key (or prompt for it on first run);
  2. validate it against Keygen, *scoped to this machine's fingerprint*;
  3. if the machine isn't activated yet, activate it (node-locked: one machine
     per key, enforced by the Keygen policy);
  4. allow the app only if the license is valid.

Security notes:
  * The public ``validate-key`` endpoint needs no admin token, so nothing
    secret is embedded in the client. The account id is not secret.
  * Purely client-side checks can be patched out of any local binary; this
    raises the bar and gives you real control (revoke/suspend a key, see active
    machines), but isn't unbreakable. See README for hardening options.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
import uuid

from .i18n import t

# Empty = licensing disabled (the app is free/open). The gate in app.main() is
# also removed; this module is kept dormant in case licensing is wanted later.
KEYGEN_ACCOUNT_ID = ""

_API = "https://api.keygen.sh/v1/accounts/{account}"
_JSON = "application/vnd.api+json"

# Codes that mean "key is fine, this machine just needs activating".
_ACTIVATE_CODES = {"NO_MACHINE", "NO_MACHINES", "FINGERPRINT_SCOPE_MISMATCH"}


def _code_msg(lang: str, code: str) -> str:
    key = f"code_{code}"
    msg = t(lang, key)
    return msg if msg != key else t(lang, "code_INVALID", code=code or "error")


def account_id(cfg) -> str:
    # The baked-in account id always wins, so nobody can point the app at a
    # different Keygen account by editing config.json. The config value is only
    # a fallback during development (when nothing is baked in).
    return (KEYGEN_ACCOUNT_ID or getattr(cfg, "keygen_account_id", "") or "").strip()


def machine_fingerprint() -> str:
    """A stable per-machine id (Windows MachineGuid, with a MAC fallback)."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            if guid:
                return str(guid)
    except Exception:
        pass
    return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:36]


def _api_post(url: str, body: dict, extra_headers: dict | None = None):
    """POST JSON:API and return (status, parsed_json). Raises urllib URLError
    only when the server is unreachable (caller treats that as 'offline')."""
    headers = {"Content-Type": _JSON, "Accept": _JSON}
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.getcode(), json.loads(raw)
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a JSON body
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        return exc.code, payload


def _activate_machine(account: str, key: str, license_id: str, fingerprint: str):
    """Activate this machine. Returns (ok, error_code)."""
    url = _API.format(account=account) + "/machines"
    body = {
        "data": {
            "type": "machines",
            "attributes": {"fingerprint": fingerprint},
            "relationships": {
                "license": {"data": {"type": "licenses", "id": license_id}}
            },
        }
    }
    status, resp = _api_post(url, body, {"Authorization": f"License {key}"})
    if status in (200, 201) and not resp.get("errors"):
        return True, ""
    errors = resp.get("errors") or []
    code = errors[0].get("code", "") if errors else ""
    print(f"[license] machine activation failed ({status}): {errors}")
    return False, code


def validate(account: str, key: str, lang: str = "en") -> tuple[str, str]:
    """Return (state, message) where state is 'valid' | 'invalid' | 'offline'."""
    url = _API.format(account=account) + "/licenses/actions/validate-key"
    fp = machine_fingerprint()
    body = {"meta": {"key": key, "scope": {"fingerprint": fp}}}
    try:
        _status, resp = _api_post(url, body)
    except urllib.error.URLError as exc:  # no network / DNS / timeout
        print(f"[license] offline: {exc}")
        return "offline", t(lang, "lic_offline_retry")

    meta = resp.get("meta") or {}
    if meta.get("valid"):
        return "valid", "OK"

    code = meta.get("code") or ""
    license_id = (resp.get("data") or {}).get("id")

    # Machine not activated yet -> activate this one, then re-validate.
    if code in _ACTIVATE_CODES and license_id:
        ok, err = _activate_machine(account, key, license_id, fp)
        if ok:
            try:
                _status, resp2 = _api_post(url, body)
            except urllib.error.URLError:
                return "offline", t(lang, "lic_offline_retry")
            if (resp2.get("meta") or {}).get("valid"):
                return "valid", "OK"
            code = (resp2.get("meta") or {}).get("code") or code
        elif err == "LICENSE_NOT_ALLOWED":
            return "invalid", t(lang, "lic_not_allowed")
        elif err in ("MACHINE_LIMIT_EXCEEDED", "TOO_MANY_MACHINES"):
            return "invalid", t(lang, "code_MACHINE_LIMIT_EXCEEDED")
        else:
            return "invalid", _code_msg(lang, err) if err else t(lang, "lic_activate_fail")

    return "invalid", _code_msg(lang, code)


# ---- UI prompts (tkinter) ----------------------------------------------------
def _prompt_for_key(lang: str = "en", current: str = "",
                    error: str | None = None) -> str | None:
    """Show the activation window. Returns the entered key, or None if cancelled."""
    import tkinter as tk

    result: dict = {"key": None}
    root = tk.Tk()
    root.title(t(lang, "lic_title"))
    root.configure(bg="#1b1b22")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    frm = tk.Frame(root, bg="#1b1b22", padx=22, pady=18)
    frm.pack()

    tk.Label(frm, text=t(lang, "lic_header"), bg="#1b1b22", fg="#e6e6ea",
             font=("Segoe UI", 13, "bold")).pack(anchor="w")
    tk.Label(frm, text=t(lang, "lic_prompt"),
             bg="#1b1b22", fg="#a8a8b3", font=("Segoe UI", 10),
             justify="left").pack(anchor="w", pady=(2, 10))

    if error:
        tk.Label(frm, text=error, bg="#1b1b22", fg="#ff6b6b", wraplength=360,
                 font=("Segoe UI", 9), justify="left").pack(anchor="w", pady=(0, 8))

    var = tk.StringVar(value=current)
    entry = tk.Entry(frm, textvariable=var, width=40, font=("Consolas", 11),
                     bg="#2a2a33", fg="#ffffff", insertbackground="#ffffff",
                     relief="flat")
    entry.pack(fill="x", ipady=5, pady=(0, 14))
    entry.focus_set()

    def ok(*_):
        result["key"] = var.get().strip()
        root.destroy()

    def cancel(*_):
        result["key"] = None
        root.destroy()

    btns = tk.Frame(frm, bg="#1b1b22")
    btns.pack(fill="x")
    tk.Button(btns, text=t(lang, "activate"), command=ok, width=12, relief="flat",
              bg="#51cf66", fg="#10220f", activebackground="#69db7c",
              font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="right")
    tk.Button(btns, text=t(lang, "cancel"), command=cancel, width=10, relief="flat",
              bg="#3a3a44", fg="#e6e6ea", activebackground="#4a4a55",
              font=("Segoe UI", 10), cursor="hand2").pack(side="right", padx=(0, 8))

    root.bind("<Return>", ok)
    root.bind("<Escape>", cancel)
    root.protocol("WM_DELETE_WINDOW", cancel)

    # Centre on screen.
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
    root.mainloop()
    return result["key"]


def _show_error(lang: str, message: str) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        messagebox.showerror(t(lang, "lic_err_title"), message, parent=root)
    finally:
        root.destroy()


def _mark_valid(cfg, key: str) -> None:
    cfg.license_key = key
    cfg.license_last_valid = time.time()
    try:
        cfg.save()
    except Exception:
        pass
    print("[license] valid")


def _within_grace(cfg, key: str) -> bool:
    last = getattr(cfg, "license_last_valid", 0) or 0
    grace = getattr(cfg, "license_grace_days", 14) * 86400
    stored = (getattr(cfg, "license_key", "") or "").strip()
    return bool(last) and key == stored and (time.time() - last) < grace


def ensure_licensed(cfg) -> bool:
    """Gate the app behind a valid license. Returns True if allowed to run.

    A valid stored key starts the app silently (no popup). The activation
    window only appears when there is no key, or the stored one is invalid.
    """
    account = account_id(cfg)
    if not account:
        print("[license] not configured (no keygen_account_id) -> running unlocked")
        return True

    lang = getattr(cfg, "language", "en")
    error: str | None = None

    # 1) Try the stored key silently first.
    stored = (getattr(cfg, "license_key", "") or "").strip()
    if stored:
        state, message = validate(account, stored, lang)
        if state == "valid":
            _mark_valid(cfg, stored)
            return True
        if state == "offline":
            if _within_grace(cfg, stored):
                print("[license] offline but within grace period -> allowed")
                return True
            _show_error(lang, t(lang, "lic_offline_stored"))
            return False
        error = message  # invalid -> fall through to the prompt

    # 2) Prompt the user (with any error shown in the window) and retry.
    for _attempt in range(4):
        entered = _prompt_for_key(lang, error=error)
        if entered is None:
            return False  # cancelled
        entered = entered.strip()
        if not entered:
            error = t(lang, "lic_empty")
            continue
        state, message = validate(account, entered, lang)
        if state == "valid":
            _mark_valid(cfg, entered)
            return True
        if state == "offline":
            error = t(lang, "lic_offline_retry")
            continue
        error = message

    return False

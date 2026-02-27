import datetime
import json
import os
import random
import re
import tempfile
import urllib.error
import urllib.request
from copy import deepcopy

import streamlit as st

BOT_NAME = "Manasyee AI"
MEMORY_FILE = "memory.json"
MEMORY_SCHEMA_VERSION = "1.1"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")
THEME_PRESETS = {
    "Dreamy": {
        "bg_1": "#0f0722",
        "bg_2": "#25103f",
        "bg_3": "#1d0f32",
        "orb_1": "rgba(255, 145, 219, 0.25)",
        "orb_2": "rgba(172, 149, 255, 0.2)",
        "text_main": "#fff6fd",
        "text_soft": "#f6dff0",
        "card_border": "rgba(255, 193, 233, 0.35)",
        "button_top": "#ff82d3",
        "button_bottom": "#e95fc0",
    },
    "Rose Gold": {
        "bg_1": "#241019",
        "bg_2": "#4d1f35",
        "bg_3": "#2f1321",
        "orb_1": "rgba(255, 188, 156, 0.26)",
        "orb_2": "rgba(255, 130, 179, 0.2)",
        "text_main": "#fff4f6",
        "text_soft": "#ffdfe9",
        "card_border": "rgba(255, 208, 222, 0.38)",
        "button_top": "#ff9bc9",
        "button_bottom": "#ef6aa8",
    },
    "Night Sky": {
        "bg_1": "#08121f",
        "bg_2": "#12304b",
        "bg_3": "#0a1d31",
        "orb_1": "rgba(109, 186, 255, 0.24)",
        "orb_2": "rgba(142, 170, 255, 0.2)",
        "text_main": "#ecf7ff",
        "text_soft": "#cae9ff",
        "card_border": "rgba(170, 220, 255, 0.35)",
        "button_top": "#5fa8ff",
        "button_bottom": "#3b7ed9",
    },
    "Dark": {
        "bg_1": "#0b070d",
        "bg_2": "#1a101f",
        "bg_3": "#130a18",
        "orb_1": "rgba(198, 119, 164, 0.18)",
        "orb_2": "rgba(126, 103, 170, 0.16)",
        "text_main": "#f5edf8",
        "text_soft": "#d9c6df",
        "card_border": "rgba(162, 126, 181, 0.35)",
        "button_top": "#4a2d58",
        "button_bottom": "#2f1c39",
    },
}

st.set_page_config(
    page_title=BOT_NAME,
    page_icon="\U0001F497",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def get_config_value(key, default=""):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        # No secrets.toml configured; fall back to environment/default.
        pass
    return os.getenv(key, default)


MODEL_NAME = get_config_value("MODEL_NAME", "arcee-ai/trinity-large-preview:free")
OPENAI_BASE_URL = get_config_value("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_API_KEY = get_config_value("OPENROUTER_API_KEY", "") or get_config_value("OPENAI_API_KEY", "")
# Backward-compatible alias for existing call sites.
OPENAI_API_KEY = OPENROUTER_API_KEY
OPENROUTER_SITE_URL = get_config_value("OPENROUTER_SITE_URL", "")
OPENROUTER_APP_NAME = get_config_value("OPENROUTER_APP_NAME", BOT_NAME)
OPENROUTER_MAX_AUTO_CONTINUES = int(get_config_value("OPENROUTER_MAX_AUTO_CONTINUES", "4"))


DEFAULT_MEMORY = {
    "name": "Manasyee",
    "preferred_name": "Manasyee",
    "creator_name": "Jordan",
    "recipient_name": "Manasyee",
    "birthday": "2005-04-22",
    "studies": "law",
    "career_goal": "to be a lawyer",
    "likes": [],
    "music_artists": [],
    "movies_shows": [],
    "food_favorites": [],
    "notes": [],
    "period_cycles": [],
    "period_settings": {
        "use_manual_cycle_length": False,
        "manual_cycle_length": 28,
        "luteal_days": 14,
    },
    "ui_message_pools": {},
    "_ui_rotation": {},
    "_version": MEMORY_SCHEMA_VERSION,
    "_updated_at": "",
    "_last_updated_by": "system",
    "_memory_log": [],
}


class MemoryStore:
    def __init__(self, path, defaults):
        self.path = path
        self.defaults = defaults
        self.data = {}
        self.last_mtime = None
        self.load()

    def _now_iso(self):
        return datetime.datetime.now(IST).isoformat()

    def _operation(self, ok, action, key=None, message=""):
        return {"ok": ok, "action": action, "key": key, "message": message}

    def _atomic_write(self):
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder, delete=False) as tmp:
                json.dump(self.data, tmp, indent=2, ensure_ascii=False)
                tmp_path = tmp.name
            os.replace(tmp_path, self.path)
            self.last_mtime = os.path.getmtime(self.path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _ensure_schema(self, raw):
        base = raw if isinstance(raw, dict) else {}
        for key, default_value in self.defaults.items():
            if key not in base:
                base[key] = deepcopy(default_value)
            else:
                if isinstance(default_value, list) and not isinstance(base[key], list):
                    base[key] = []
                if isinstance(default_value, dict) and not isinstance(base[key], dict):
                    base[key] = {}
        base["_version"] = MEMORY_SCHEMA_VERSION
        base.setdefault("_updated_at", "")
        base.setdefault("_last_updated_by", "system")
        base.setdefault("_memory_log", [])
        if not isinstance(base["_memory_log"], list):
            base["_memory_log"] = []
        return base

    def _replace_data(self, new_data):
        self.data.clear()
        self.data.update(new_data)

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
        normalized = self._ensure_schema(raw)
        self._replace_data(normalized)
        try:
            self.last_mtime = os.path.getmtime(self.path)
        except OSError:
            self.last_mtime = None

    def reload_if_changed(self):
        try:
            current = os.path.getmtime(self.path)
        except OSError:
            current = None
        if current != self.last_mtime:
            self.load()

    def _touch_meta(self, action, key, updated_by):
        now = self._now_iso()
        self.data["_version"] = MEMORY_SCHEMA_VERSION
        self.data["_updated_at"] = now
        self.data["_last_updated_by"] = updated_by
        log = self.data.setdefault("_memory_log", [])
        log.append({"ts": now, "action": action, "key": key})
        if len(log) > 200:
            del log[:-200]

    def save(self, action="save", key=None, updated_by="system"):
        self._touch_meta(action=action, key=key, updated_by=updated_by)
        self._atomic_write()
        return self._operation(True, action, key, "saved")

    def get(self, key, default=None):
        self.reload_if_changed()
        return self.data.get(key, default)

    def set(self, key, value, updated_by="user"):
        self.reload_if_changed()
        self.data[key] = value
        return self.save(action="set", key=key, updated_by=updated_by)

    def append_unique(self, key, value, updated_by="user"):
        self.reload_if_changed()
        container = self.data.setdefault(key, [])
        if not isinstance(container, list):
            return self._operation(False, "append", key, "not_a_list")
        if any(str(item).strip().lower() == str(value).strip().lower() for item in container):
            return self._operation(False, "append", key, "duplicate")
        container.append(value)
        return self.save(action="append", key=key, updated_by=updated_by)

    def delete_key(self, key, updated_by="user"):
        self.reload_if_changed()
        if key not in self.data:
            return self._operation(False, "delete_key", key, "missing")
        del self.data[key]
        return self.save(action="delete_key", key=key, updated_by=updated_by)

    def delete_from_list(self, key, value, updated_by="user"):
        self.reload_if_changed()
        if key not in self.data:
            return self._operation(False, "delete_item", key, "missing")
        if not isinstance(self.data[key], list):
            return self._operation(False, "delete_item", key, "not_a_list")
        before = len(self.data[key])
        self.data[key] = [x for x in self.data[key] if str(x).strip().lower() != str(value).strip().lower()]
        if len(self.data[key]) == before:
            return self._operation(False, "delete_item", key, "item_missing")
        return self.save(action="delete_item", key=key, updated_by=updated_by)


def invalidate_memory_caches():
    st.session_state.pop("memory_index_cache", None)
    st.session_state.pop("memory_prompt_cache", None)

memory_store = MemoryStore(MEMORY_FILE, DEFAULT_MEMORY)
memory = memory_store.data
NAME = memory.get("preferred_name") or memory.get("recipient_name") or memory.get("name") or "Manasyee"


def save_memory():
    result = memory_store.save(action="save", key="*", updated_by="system")
    invalidate_memory_caches()
    return result


def memory_get(key, default=None):
    return memory_store.get(key, default)


def memory_set(key, value, updated_by="user"):
    result = memory_store.set(key, value, updated_by=updated_by)
    invalidate_memory_caches()
    return result


def memory_append(key, value, updated_by="user"):
    result = memory_store.append_unique(key, value, updated_by=updated_by)
    invalidate_memory_caches()
    return result


def memory_delete(key, value=None, updated_by="user"):
    if value is None:
        result = memory_store.delete_key(key, updated_by=updated_by)
    else:
        result = memory_store.delete_from_list(key, value, updated_by=updated_by)
    invalidate_memory_caches()
    return result

DEFAULT_MESSAGE_POOLS = {
    "jordan_messages": [
        "Hey Manasyee! May all your impossible dreams come true and you truly become limitless.",
        "Jordan says: your glow-up arc is real, keep going queen.",
        "Jordan says: your future self is already proud of you.",
        "Jordan says: one focused step today beats ten perfect plans.",
        "Jordan says: you are stronger than the day feels.",
    ],
    "mood_boosters": [
        "Hydrate + breathe + you're doing better than you think.",
        "Small win check: you showed up today, and that counts.",
        "Soft reminder: rest is productive too.",
        "One deep breath now, one brave step next.",
        "You are not behind, you are building.",
    ],
    "study_nudges": [
        "15 min focus sprint - villain arc defeated.",
        "Pick one task, set a timer, no overthinking.",
        "Read 2 pages now; momentum will do the rest.",
        "Law grind tip: summarize one concept in your own words.",
        "Do a 20-minute deep-work block, then reward yourself.",
    ],
}

STRUCTURED_MEMORY_MAP = {
    "profile": ["name", "preferred_name", "recipient_name", "creator_name", "birthday", "zodiac"],
    "education_career": ["studies", "career_goal"],
    "preferences": ["likes", "food_favorites", "music_artists", "movies_shows"],
    "notes": ["notes"],
}

IGNORED_MEMORY_KEYS = {"ui_message_pools", "_ui_rotation"}
STOPWORDS = {
    "what",
    "when",
    "where",
    "who",
    "is",
    "are",
    "the",
    "a",
    "an",
    "my",
    "me",
    "tell",
    "about",
    "do",
    "does",
    "for",
    "to",
    "and",
    "of",
    "in",
    "on",
    "with",
    "please",
}


def get_message_pool(pool_key):
    custom_pools = memory.get("ui_message_pools", {})
    custom_pool = custom_pools.get(pool_key) if isinstance(custom_pools, dict) else None
    if isinstance(custom_pool, list):
        cleaned = [m for m in custom_pool if isinstance(m, str) and m.strip()]
        if cleaned:
            return cleaned
    return DEFAULT_MESSAGE_POOLS[pool_key]


def pick_rotating_message(pool_key):
    pool = get_message_pool(pool_key)
    rotation = memory.setdefault("_ui_rotation", {})
    used = rotation.setdefault(pool_key, [])
    if not isinstance(used, list):
        used = []
        rotation[pool_key] = used

    available = [m for m in pool if m not in used]
    if not available:
        used.clear()
        available = pool[:]

    choice = random.choice(available)
    used.append(choice)
    save_memory()
    return choice


def generate_quick_action_reply(action_key):
    prompts = {
        "jordan": (
            "Write a short flirty note to Manasyee. "
            "Keep it playful, sweet, and light; avoid intensely romantic language."
        ),
        "study": (
            "Write a concise study nudge addressed directly to Manasyee: "
            "one motivating line and one concrete next step."
        ),
        "mood": (
            "Write a concise mood booster addressed directly to Manasyee: "
            "one comforting line and one tiny action."
        ),
    }
    prompt = prompts.get(action_key)
    if not prompt:
        return "Unknown quick action."

    fallback_pool_map = {
        "jordan": "jordan_messages",
        "study": "study_nudges",
        "mood": "mood_boosters",
    }

    def _quick_action_fallback():
        pool_key = fallback_pool_map.get(action_key)
        if not pool_key:
            return "Could not generate quick action right now."
        fallback_text = pick_rotating_message(pool_key)
        if not isinstance(fallback_text, str):
            fallback_text = str(fallback_text)
        fallback_text = fallback_text.strip()
        if "manasyee" not in fallback_text.lower():
            fallback_text = f"Manasyee, {fallback_text}"
        lines = [line.strip() for line in fallback_text.splitlines() if line.strip()]
        return "\n".join(lines[:2]) if lines else fallback_text

    if not OPENAI_API_KEY:
        return _quick_action_fallback()
    if not OPENAI_BASE_URL:
        return _quick_action_fallback()

    system_prompt = (
        "You are Mana in quick-actions mode. "
        "Do not use or reference saved memory. "
        "Return concise, supportive text only."
    )
    nonce = f"{datetime.datetime.now(IST).isoformat()}-{random.randint(1000, 9999)}"
    seen = st.session_state.setdefault("quick_action_seen", {})
    seen_for_action = seen.setdefault(action_key, [])
    avoid_text = "\n".join(f"- {item}" for item in seen_for_action[-5:])

    user_prompt = (
        f"{prompt}\n"
        "Return only final text. Maximum 2 short lines.\n"
        "Make this response feel new.\n"
        f"Unique nonce: {nonce}\n"
    )
    if avoid_text:
        user_prompt += f"Avoid repeating these prior outputs:\n{avoid_text}\n"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL
    if OPENROUTER_APP_NAME:
        headers["X-Title"] = OPENROUTER_APP_NAME

    def _call_quick_model(user_text, temperature=0.75):
        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": temperature,
            "top_p": 0.9,
            "max_tokens": 80,
        }
        req = urllib.request.Request(
            f"{OPENAI_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if isinstance(data, dict) and data.get("error"):
            err = data.get("error")
            if isinstance(err, dict):
                raise RuntimeError(err.get("message") or "Unknown quick-action model error.")
            raise RuntimeError(str(err))

        choices = data.get("choices") or []
        if not choices:
            return ""
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message", {}) if isinstance(first.get("message"), dict) else {}
        content = message.get("content")

        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text_piece = item.get("text")
                if isinstance(text_piece, str) and text_piece.strip():
                    parts.append(text_piece.strip())
            return " ".join(parts).strip()
        alt_text = first.get("text")
        return alt_text.strip() if isinstance(alt_text, str) else ""

    try:
        text = _call_quick_model(user_prompt, temperature=0.75)

        if not isinstance(text, str) or not text.strip():
            retry_prompt = (
                f"{prompt}\n"
                "Reply in exactly 2 short lines. Keep it simple and direct.\n"
                f"Unique nonce: {nonce}-retry\n"
            )
            text = _call_quick_model(retry_prompt, temperature=0.6)
        if not isinstance(text, str) or not text.strip():
            return _quick_action_fallback()
        text = text.strip()
        if "manasyee" not in text.lower():
            text = f"Manasyee, {text}"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines[:2]) if lines else text
        seen_for_action.append(text)
        if len(seen_for_action) > 40:
            del seen_for_action[:-40]
        return text
    except urllib.error.HTTPError as e:
        details = ""
        try:
            raw = e.read().decode("utf-8", errors="ignore")
            parsed = json.loads(raw) if raw else {}
            details = parsed.get("error", {}).get("message") or parsed.get("message") or ""
        except Exception:
            details = ""
        if e.code in {401, 403}:
            return _quick_action_fallback()
        if e.code == 429:
            return _quick_action_fallback()
        return _quick_action_fallback()
    except urllib.error.URLError:
        return _quick_action_fallback()
    except Exception as e:
        return _quick_action_fallback()


def _ensure_chat_state():
    st.session_state.setdefault("msgs", [])


def _push_assistant_message(text):
    _ensure_chat_state()
    st.session_state.msgs.append({"role": "assistant", "content": text})


def _today_iso():
    return datetime.datetime.now(IST).date().isoformat()


def _now_ts():
    return datetime.datetime.now(IST).timestamp()


def _get_focus_stats():
    stats = memory.get("focus_stats", {})
    if not isinstance(stats, dict):
        stats = {}
    stats.setdefault("streak", 0)
    stats.setdefault("last_focus_date", "")
    stats.setdefault("total_sessions", 0)
    stats.setdefault("total_minutes", 0)
    return stats


def _save_focus_stats(stats):
    memory_set("focus_stats", stats, updated_by="system")


def _init_focus_state():
    today = _today_iso()
    state = st.session_state.setdefault(
        "focus_state",
        {
            "active": False,
            "paused": False,
            "phase": "focus",
            "mode": "idle",
            "task": "",
            "duration_min": 25,
            "started_ts": 0.0,
            "end_ts": 0.0,
            "remaining_sec": 0,
            "halfway_sent": False,
            "prompt_sent": False,
            "break_coach_sent": False,
            "today_date": today,
            "today_sessions": 0,
            "today_minutes": 0,
        },
    )
    if state.get("today_date") != today:
        state["today_date"] = today
        state["today_sessions"] = 0
        state["today_minutes"] = 0
    return state


def _start_focus_timer(duration_min, mode, task_text, phase="focus"):
    state = _init_focus_state()
    now_ts = _now_ts()
    state["active"] = True
    state["paused"] = False
    state["phase"] = phase
    state["mode"] = mode
    state["task"] = task_text.strip() if task_text else state.get("task", "")
    state["duration_min"] = int(duration_min)
    state["started_ts"] = now_ts
    state["end_ts"] = now_ts + (int(duration_min) * 60)
    state["remaining_sec"] = int(duration_min) * 60
    state["halfway_sent"] = False
    state["prompt_sent"] = False
    state["break_coach_sent"] = False


def _reset_focus_timer():
    state = _init_focus_state()
    state["active"] = False
    state["paused"] = False
    state["phase"] = "focus"
    state["mode"] = "idle"
    state["duration_min"] = 25
    state["started_ts"] = 0.0
    state["end_ts"] = 0.0
    state["remaining_sec"] = 0
    state["halfway_sent"] = False
    state["prompt_sent"] = False
    state["break_coach_sent"] = False


def _update_streak_and_totals(minutes_done):
    stats = _get_focus_stats()
    today = datetime.datetime.now(IST).date()
    today_iso = today.isoformat()
    last_date_raw = stats.get("last_focus_date", "")
    prior_streak = int(stats.get("streak", 0) or 0)

    try:
        last_date = datetime.date.fromisoformat(last_date_raw) if last_date_raw else None
    except Exception:
        last_date = None

    if last_date == today:
        new_streak = prior_streak
    elif last_date == (today - datetime.timedelta(days=1)):
        new_streak = prior_streak + 1
    else:
        new_streak = 1

    stats["last_focus_date"] = today_iso
    stats["streak"] = new_streak
    stats["total_sessions"] = int(stats.get("total_sessions", 0) or 0) + 1
    stats["total_minutes"] = int(stats.get("total_minutes", 0) or 0) + int(minutes_done)
    _save_focus_stats(stats)


def _tick_focus_state():
    state = _init_focus_state()
    if not state["active"] or state["paused"]:
        return

    now_ts = _now_ts()
    remaining = int(state["end_ts"] - now_ts)
    state["remaining_sec"] = max(0, remaining)

    if state["phase"] == "focus":
        half_sec = int(state["duration_min"] * 60 / 2)
        elapsed = int(now_ts - state["started_ts"])
        if elapsed >= half_sec and not state["halfway_sent"]:
            task_txt = state.get("task", "").strip() or "your current task"
            _push_assistant_message(f"Manasyee, halfway done. Stay with {task_txt} for this block.")
            state["halfway_sent"] = True

    if remaining > 0:
        return

    state["active"] = False
    state["paused"] = False
    state["remaining_sec"] = 0

    if state["phase"] == "focus":
        state["today_sessions"] += 1
        state["today_minutes"] += int(state["duration_min"])
        _update_streak_and_totals(state["duration_min"])
        _push_assistant_message("Manasyee, focus session complete. Log one win from this block.")

        if state["mode"] == "pomodoro":
            _start_focus_timer(duration_min=5, mode="pomodoro", task_text=state.get("task", ""), phase="break")
            _push_assistant_message(
                "Manasyee, break coach: water, shoulder stretch, 5 deep breaths, look away from screen, then come back."
            )
    else:
        _push_assistant_message("Manasyee, break complete. Ready for your next focus sprint?")
        state["mode"] = "idle"
        state["phase"] = "focus"


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except Exception:
        return None


def _load_period_cycles():
    raw = memory.get("period_cycles", [])
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start_date = _parse_iso_date(item.get("start_date"))
        end_date = _parse_iso_date(item.get("end_date"))
        if not start_date:
            continue
        if end_date and end_date < start_date:
            end_date = None
        cleaned.append(
            {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat() if end_date else "",
                "note": str(item.get("note", "")).strip(),
            }
        )
    cleaned.sort(key=lambda x: x["start_date"])
    return cleaned


def _save_period_cycles(cycles):
    memory_set("period_cycles", cycles, updated_by="user")


def _get_period_settings():
    raw = memory.get("period_settings", {})
    if not isinstance(raw, dict):
        raw = {}
    settings = {
        "use_manual_cycle_length": bool(raw.get("use_manual_cycle_length", False)),
        "manual_cycle_length": int(raw.get("manual_cycle_length", 28) or 28),
        "luteal_days": int(raw.get("luteal_days", 14) or 14),
    }
    settings["manual_cycle_length"] = max(21, min(45, settings["manual_cycle_length"]))
    settings["luteal_days"] = max(10, min(16, settings["luteal_days"]))
    return settings


def _save_period_settings(settings):
    memory_set("period_settings", settings, updated_by="user")


def _cycle_lengths(cycles):
    starts = [_parse_iso_date(item.get("start_date")) for item in cycles]
    starts = [d for d in starts if d]
    if len(starts) < 2:
        return []
    return [(starts[i] - starts[i - 1]).days for i in range(1, len(starts))]


def _period_lengths(cycles):
    lengths = []
    for item in cycles:
        start_date = _parse_iso_date(item.get("start_date"))
        end_date = _parse_iso_date(item.get("end_date"))
        if start_date and end_date and end_date >= start_date:
            lengths.append((end_date - start_date).days + 1)
    return lengths


def _predict_period(cycles):
    if not cycles:
        return None

    starts = [_parse_iso_date(item.get("start_date")) for item in cycles]
    starts = [d for d in starts if d]
    if not starts:
        return None

    settings = _get_period_settings()
    last_start = starts[-1]
    all_lengths = _cycle_lengths(cycles)
    recent_lengths = all_lengths[-6:]
    valid_lengths = [d for d in recent_lengths if 18 <= d <= 60]

    if valid_lengths and not settings["use_manual_cycle_length"]:
        weights = list(range(1, len(valid_lengths) + 1))
        weighted_avg = sum(v * w for v, w in zip(valid_lengths, weights)) / float(sum(weights))
        avg_cycle = int(round(weighted_avg))
        variability = int(round(sum(abs(v - avg_cycle) for v in valid_lengths) / len(valid_lengths)))
    else:
        avg_cycle = int(settings["manual_cycle_length"])
        variability = 4

    avg_cycle = max(21, min(45, avg_cycle))
    variability = max(1, min(7, variability))

    next_start = last_start + datetime.timedelta(days=avg_cycle)
    ovulation_estimate = next_start - datetime.timedelta(days=int(settings["luteal_days"]))
    fertile_start = ovulation_estimate - datetime.timedelta(days=5)
    fertile_end = ovulation_estimate + datetime.timedelta(days=1)
    pms_start = next_start - datetime.timedelta(days=5)

    if len(valid_lengths) >= 6 and variability <= 1:
        confidence = "High"
    elif len(valid_lengths) >= 4 and variability <= 2:
        confidence = "Medium"
    elif settings["use_manual_cycle_length"] and len(valid_lengths) >= 2:
        confidence = "Medium"
    else:
        confidence = "Low"

    today = datetime.datetime.now(IST).date()
    cycle_day = (today - last_start).days + 1 if today >= last_start else None
    period_len_samples = _period_lengths(cycles)
    avg_period_len = int(round(sum(period_len_samples) / len(period_len_samples))) if period_len_samples else None

    return {
        "next_start": next_start,
        "avg_cycle": avg_cycle,
        "variability": variability,
        "confidence": confidence,
        "cycle_day": cycle_day,
        "fertile_start": fertile_start,
        "fertile_end": fertile_end,
        "ovulation_estimate": ovulation_estimate,
        "pms_start": pms_start,
        "sample_count": len(valid_lengths),
        "avg_period_len": avg_period_len,
        "source": "manual" if settings["use_manual_cycle_length"] or not valid_lengths else "learned",
        "luteal_days": int(settings["luteal_days"]),
    }


def _current_cycle_phase(prediction, today_date):
    if not prediction:
        return "Unknown"
    next_start = prediction.get("next_start")
    if not isinstance(next_start, datetime.date):
        return "Unknown"

    fertile_start = prediction.get("fertile_start")
    fertile_end = prediction.get("fertile_end")
    ovulation_estimate = prediction.get("ovulation_estimate")
    pms_start = prediction.get("pms_start")
    avg_period_len = int(prediction.get("avg_period_len") or 5)
    avg_period_len = max(3, min(8, avg_period_len))

    cycle_start = next_start - datetime.timedelta(days=int(prediction.get("avg_cycle", 28)))
    cycle_day = (today_date - cycle_start).days + 1

    if cycle_day <= avg_period_len and cycle_day > 0:
        return "Menstrual"
    if isinstance(fertile_start, datetime.date) and isinstance(fertile_end, datetime.date):
        if fertile_start <= today_date <= fertile_end:
            if isinstance(ovulation_estimate, datetime.date) and today_date == ovulation_estimate:
                return "Ovulation"
            return "Fertile Window"
    if isinstance(pms_start, datetime.date) and pms_start <= today_date < next_start:
        return "PMS"
    if cycle_day > 0 and cycle_day < (int(prediction.get("avg_cycle", 28)) // 2):
        return "Follicular"
    return "Luteal"


def _set_period_chip(key, message, tone="success"):
    st.session_state[key] = {"message": str(message), "tone": str(tone)}


def _render_period_chip(key):
    payload = st.session_state.pop(key, None)
    if not isinstance(payload, dict):
        return
    tone = payload.get("tone", "success")
    cls = "chip-info" if tone == "info" else "chip-success"
    text = payload.get("message", "")
    icon = "\u2139\uFE0F" if tone == "info" else "\u2705"
    st.markdown(
        f"<div class='inline-chip {cls}'>{icon} {text}</div>",
        unsafe_allow_html=True,
    )


def render_period_tracker():
    show_how_it_works = st.toggle(
        "How it works + reliability",
        value=False,
        key="period_help_toggle_how_it_works",
    )
    if show_how_it_works:
        st.markdown(
            """
How to use:
1. Add each period start date and include end date when available.
2. Set your typical cycle length if your logs are limited.
3. Keep logging monthly; prediction quality improves with more entries.
4. Use predictions for planning and reminders, not diagnosis.

What this tracker does:
- Learns your average cycle length from logged history.
- Predicts the next estimated period date and range window.
- Estimates fertile window, ovulation day, and PMS window.
- Shows confidence level based on consistency of your recent cycles.

Effectiveness:
- Best for cycle planning and reminders, especially with regular cycles.
- Typically more reliable after at least 4-6 logged cycle starts.
- Lower confidence for irregular cycles, missing entries, or sudden pattern changes.
- Not a medical tool; consult a clinician for diagnosis or persistent symptoms.
"""
        )

    show_cycle_phase_guide = st.toggle(
        "Cycle phase quick guide",
        value=False,
        key="period_help_toggle_phase_guide",
    )
    if show_cycle_phase_guide:
        st.markdown(
            """
- Menstrual: Period bleeding days; energy may be lower.
- Follicular: After period; energy and focus usually rise.
- Fertile Window: Highest pregnancy likelihood days.
- Ovulation: Egg release day; peak fertility.
- Luteal: Post-ovulation phase before next period.
- PMS: Late luteal days; common mood/body symptoms.
"""
        )

    cycles = _load_period_cycles()
    settings = _get_period_settings()
    today = datetime.datetime.now(IST).date()

    st.markdown("### Prediction Settings")
    _render_period_chip("period_settings_chip")
    s1, s2, s3 = st.columns(3)
    manual_toggle = s1.toggle(
        "Use manual cycle length",
        value=bool(settings["use_manual_cycle_length"]),
        key="period_use_manual_toggle",
    )
    manual_len = s2.number_input(
        "Cycle length (days)",
        min_value=21,
        max_value=45,
        value=int(settings["manual_cycle_length"]),
        step=1,
        key="period_manual_cycle_len",
    )
    luteal_days = s3.number_input(
        "Luteal phase (days)",
        min_value=10,
        max_value=16,
        value=int(settings["luteal_days"]),
        step=1,
        key="period_luteal_days",
    )
    if st.button("Save period settings", use_container_width=True, key="period_save_settings"):
        new_settings = {
            "use_manual_cycle_length": bool(manual_toggle),
            "manual_cycle_length": int(manual_len),
            "luteal_days": int(luteal_days),
        }
        _save_period_settings(new_settings)
        _set_period_chip("period_settings_chip", "Period settings saved.")
        st.rerun()

    st.markdown("### Log Cycle")
    _render_period_chip("period_log_chip")
    c1, c2 = st.columns(2)
    start_date = c1.date_input("Start date", value=today, key="period_start_date")
    include_end = c2.toggle("Include end date", value=False, key="period_include_end")
    end_date = st.date_input("End date", value=today, key="period_end_date") if include_end else None
    note = st.text_input("Optional note", value="", key="period_note")

    a1, a2 = st.columns(2)
    if a1.button("Add cycle entry", use_container_width=True, key="period_add_entry"):
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat() if include_end else ""
        if include_end and end_date < start_date:
            st.error("End date cannot be before start date.")
        elif any(item.get("start_date") == start_iso for item in cycles):
            st.warning("This start date already exists.")
        else:
            cycles.append({"start_date": start_iso, "end_date": end_iso, "note": note.strip()})
            cycles.sort(key=lambda x: x["start_date"])
            _save_period_cycles(cycles)
            _set_period_chip("period_log_chip", "Cycle entry saved.")
            st.rerun()

    delete_options = ["-"] + [item["start_date"] for item in cycles]
    delete_target = st.selectbox("Delete entry by start date", options=delete_options, key="period_delete_target")
    d1, d2 = st.columns(2)
    if d1.button("Delete selected entry", use_container_width=True, key="period_delete_selected"):
        if delete_target == "-":
            st.warning("Select a start date first.")
        else:
            updated = [item for item in cycles if item.get("start_date") != delete_target]
            _save_period_cycles(updated)
            _set_period_chip("period_log_chip", f"Deleted cycle entry: {delete_target}")
            st.rerun()
    if d2.button("Clear all cycle data", use_container_width=True, key="period_clear_all"):
        _save_period_cycles([])
        _set_period_chip("period_log_chip", "All cycle data cleared.")
        st.rerun()

    prediction = _predict_period(cycles)
    if not prediction:
        st.markdown(
            """
<div class='tracker-empty'>
  <div class='tracker-empty-title'>🩸 No cycle data yet</div>
  <div class='tracker-empty-sub'>Add your first start date to unlock predictions, phase tracking, and cycle insights.</div>
</div>
""",
            unsafe_allow_html=True,
        )
        return

    st.markdown("<div class='tracker-title'>Cycle Insights</div>", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Logged cycles", len(cycles))
    m2.metric("Avg cycle", f"{prediction['avg_cycle']} days")
    m3.metric("Next expected", prediction["next_start"].isoformat())
    m4.metric("Confidence", prediction["confidence"])
    st.markdown(
        (
            f"<div class='tracker-meta'>Prediction source: {prediction['source']} | "
            f"Luteal phase: {prediction['luteal_days']} days | "
            f"Samples used: {prediction['sample_count']}</div>"
        ),
        unsafe_allow_html=True,
    )

    if prediction["cycle_day"] is not None:
        st.caption(f"Current cycle day: {prediction['cycle_day']}")

    low_range = prediction["next_start"] - datetime.timedelta(days=prediction["variability"])
    high_range = prediction["next_start"] + datetime.timedelta(days=prediction["variability"])
    phase_now = _current_cycle_phase(prediction, today)
    st.markdown(
        f"""
<div class='tracker-grid'>
  <div class='tracker-card'>
    <div class='label'>&#x1F4C5; Predicted Window</div>
    <div class='value'>{low_range.isoformat()} to {high_range.isoformat()}</div>
  </div>
  <div class='tracker-card'>
    <div class='label'>&#x1F33F; Fertile Window</div>
    <div class='value'>{prediction['fertile_start'].isoformat()} to {prediction['fertile_end'].isoformat()}</div>
  </div>
  <div class='tracker-card'>
    <div class='label'>&#x2B50; Ovulation</div>
    <div class='value'>{prediction['ovulation_estimate'].isoformat()}</div>
  </div>
  <div class='tracker-card'>
    <div class='label'>&#x1F319; PMS</div>
    <div class='value'>Likely from {prediction['pms_start'].isoformat()}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    avg_cycle = max(21, min(45, int(prediction["avg_cycle"])))
    period_len = max(3, min(8, int(prediction.get("avg_period_len") or 5)))
    cycle_start = prediction["next_start"] - datetime.timedelta(days=avg_cycle)

    def _day_index(date_obj):
        if not isinstance(date_obj, datetime.date):
            return None
        day = (date_obj - cycle_start).days + 1
        return max(1, min(avg_cycle, day))

    def _edge(day_value):
        return ((day_value - 1) / float(avg_cycle)) * 100.0

    def _segment(day_start, day_end):
        day_start = max(1, min(avg_cycle, int(day_start)))
        day_end = max(day_start, min(avg_cycle, int(day_end)))
        left = _edge(day_start)
        width = max(0.8, _edge(day_end + 1) - _edge(day_start))
        return left, width

    fertile_start_day = _day_index(prediction["fertile_start"]) or 1
    fertile_end_day = _day_index(prediction["fertile_end"]) or fertile_start_day
    ovulation_day = _day_index(prediction["ovulation_estimate"]) or fertile_start_day
    pms_start_day = _day_index(prediction["pms_start"]) or max(1, avg_cycle - 5)
    current_day = int(prediction.get("cycle_day") or 1)
    current_day = max(1, min(avg_cycle, current_day))

    m_left, m_width = _segment(1, period_len)
    f_left, f_width = _segment(fertile_start_day, fertile_end_day)
    o_left, o_width = _segment(ovulation_day, ovulation_day)
    p_left, p_width = _segment(pms_start_day, avg_cycle)
    marker_left = _edge(current_day)

    st.markdown(
        f"""
<div class='tracker-timeline-wrap'>
  <div class='tracker-phase-line'>
    Current phase:
    <span class='tracker-phase-badge current'>{phase_now}</span>
    <span>Day {current_day} of ~{avg_cycle}</span>
  </div>
  <div class='tracker-timeline'>
    <span class='timeline-seg seg-menstrual' style='left:{m_left:.2f}%; width:{m_width:.2f}%;'></span>
    <span class='timeline-seg seg-fertile' style='left:{f_left:.2f}%; width:{f_width:.2f}%;'></span>
    <span class='timeline-seg seg-ovulation' style='left:{o_left:.2f}%; width:{o_width:.2f}%;'></span>
    <span class='timeline-seg seg-pms' style='left:{p_left:.2f}%; width:{p_width:.2f}%;'></span>
    <span class='tracker-marker' style='left:calc({marker_left:.2f}% - 1px);'></span>
  </div>
  <div class='tracker-legend'>
    <span><span class='legend-dot seg-menstrual'></span>Menstrual</span>
    <span><span class='legend-dot seg-fertile'></span>Fertile</span>
    <span><span class='legend-dot seg-ovulation'></span>Ovulation</span>
    <span><span class='legend-dot seg-pms'></span>PMS</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    if prediction["avg_period_len"] is not None:
        st.caption(f"Average period length from logs: {prediction['avg_period_len']} days")

raw_bday = memory.get("birthday", "2005-04-22")
try:
    BDAY = datetime.date.fromisoformat(raw_bday)
except Exception:
    try:
        BDAY = datetime.datetime.strptime(raw_bday, "%d %B %Y").date()
    except Exception:
        BDAY = datetime.date(2005, 4, 22)


def normalize_tokens(text):
    text = str(text).lower()
    words = re.findall(r"[a-z0-9_]+", text)
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def build_structured_memory_view():
    structured = {}
    for section, keys in STRUCTURED_MEMORY_MAP.items():
        payload = {}
        for key in keys:
            if key in memory:
                payload[key] = memory[key]
        if payload:
            structured[section] = payload
    return structured


def build_memory_index():
    indexed = []
    for key, value in memory.items():
        if key in IGNORED_MEMORY_KEYS or str(key).startswith("_"):
            continue
        pretty_key = key.replace("_", " ")
        key_tokens = set(normalize_tokens(pretty_key))
        if isinstance(value, list):
            for item in value:
                item_text = str(item).strip()
                if not item_text:
                    continue
                indexed.append(
                    {
                        "key": key,
                        "pretty_key": pretty_key,
                        "text": item_text,
                        "value_tokens": set(normalize_tokens(item_text)),
                        "key_tokens": key_tokens,
                    }
                )
        else:
            val_text = str(value).strip()
            if not val_text:
                continue
            indexed.append(
                {
                    "key": key,
                    "pretty_key": pretty_key,
                    "text": val_text,
                    "value_tokens": set(normalize_tokens(val_text)),
                    "key_tokens": key_tokens,
                }
            )
    return indexed


def memory_signature():
    return json.dumps(memory, ensure_ascii=False, sort_keys=True)


def get_cached_memory_index():
    signature = memory_signature()
    cache = st.session_state.get("memory_index_cache")
    if cache and cache.get("signature") == signature:
        return cache["index"]
    index = build_memory_index()
    st.session_state["memory_index_cache"] = {"signature": signature, "index": index}
    return index


def get_cached_memory_prompt(playfulness_value):
    signature = memory_signature()
    cache = st.session_state.get("memory_prompt_cache")
    if cache and cache.get("signature") == signature and cache.get("playfulness") == playfulness_value:
        return cache["prompt"]

    structured_view = build_structured_memory_view()
    if structured_view:
        memory_payload = structured_view
    else:
        memory_payload = memory

    if playfulness_value <= 20:
        style_rules = (
            "Tone: calm, direct, and practical. No sarcasm, no jokes, no anime references, no teasing."
        )
    elif playfulness_value <= 60:
        style_rules = (
            "Tone: warm and supportive with light personality. Keep humor minimal and avoid sarcasm."
        )
    else:
        style_rules = (
            "Tone: playful, caring, lightly sarcastic, anime-aware when natural."
        )

    prompt = f"""
You are Mana.
Always address the user as {NAME}.
{style_rules}
Use saved memory for personal facts, preferences, routines, and relationship context.
For general knowledge questions, answer normally using your own knowledge.
If a personal fact is missing from memory, say you do not have it in memory and ask user to update memory.
Playfulness: {playfulness_value}/100.

MEMORY:
{json.dumps(memory_payload, ensure_ascii=False, indent=2)}
"""
    st.session_state["memory_prompt_cache"] = {
        "signature": signature,
        "playfulness": playfulness_value,
        "prompt": prompt,
    }
    return prompt

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;600;700&family=Sora:wght@600;700;800&display=swap');

:root {
  --bg-1: #0f0722;
  --bg-2: #25103f;
  --bg-3: #1d0f32;
  --glow: #ff8ed8;
  --accent: #ff82d3;
  --card: rgba(255, 255, 255, 0.08);
  --card-border: rgba(255, 193, 233, 0.35);
  --text-main: #fff6fd;
  --text-soft: #f6dff0;
  --app-bg:
    radial-gradient(circle at 10% 15%, rgba(255, 145, 219, 0.25), transparent 30%),
    radial-gradient(circle at 85% 10%, rgba(172, 149, 255, 0.2), transparent 28%),
    linear-gradient(145deg, var(--bg-1), var(--bg-2) 60%, #1d0f32);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
}

html, body, [data-testid="stAppViewContainer"], .stApp {
  background: var(--app-bg) !important;
}

html {
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}

.stApp {
  background: var(--app-bg);
  color: var(--text-main);
  font-family: "Quicksand", sans-serif;
  min-height: 100vh;
  min-height: 100dvh;
}

.block-container {
  max-width: 980px;
  padding-top: 0.9rem;
  padding-bottom: 6.8rem;
}

/* Remove Streamlit dark chrome (top and bottom bars) */
header[data-testid="stHeader"] {
  background: transparent !important;
}

[data-testid="stToolbar"] {
  right: 0.8rem;
}

#MainMenu,
[data-testid="stStatusWidget"],
[data-testid="stToolbar"],
[data-testid="stAppToolbar"],
[data-testid="stHeaderActionElements"] {
  display: none !important;
}

[data-testid="stToolbar"] {
  display: none !important;
}

[data-testid="stBottomBlockContainer"] {
  background: transparent !important;
  padding-top: 0.2rem;
}

[data-testid="stBottom"] {
  background: var(--app-bg) !important;
  border-top: 0 !important;
  box-shadow: none !important;
}

[data-testid="stBottom"] > div {
  background: var(--app-bg) !important;
  border-top: 0 !important;
  box-shadow: none !important;
}

[data-testid="stChatInput"] {
  background: transparent !important;
}

footer {
  background: transparent !important;
}

* {
  -webkit-tap-highlight-color: transparent;
}

div[data-testid="stSidebar"] {
  background: linear-gradient(180deg, rgba(27, 11, 43, 0.95), rgba(18, 7, 32, 0.95));
  border-right: 1px solid rgba(255, 171, 228, 0.25);
}

.hero {
  text-align: center;
  border-radius: 22px;
  padding: 18px 20px 12px 20px;
  background: linear-gradient(130deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.04));
  border: 1px solid var(--card-border);
  box-shadow: 0 0 0 1px rgba(255,255,255,0.08), 0 14px 32px rgba(8, 0, 16, 0.4);
  backdrop-filter: blur(8px);
}

.big {
  font-family: "Sora", sans-serif;
  font-size: clamp(34px, 4.8vw, 58px);
  font-weight: 800;
  letter-spacing: 0.4px;
  line-height: 1.08;
  color: var(--text-main);
  text-shadow: 0 0 12px rgba(255, 128, 214, 0.62);
  white-space: normal;
  overflow-wrap: anywhere;
}

.sub {
  margin-top: 2px;
  color: var(--text-soft);
  font-weight: 600;
  letter-spacing: 0.2px;
}

.whisper {
  margin: 10px auto 2px auto;
  max-width: 760px;
  text-align: center;
  padding: 10px 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 198, 235, 0.35);
  background: linear-gradient(140deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.04));
  color: #ffe9f7;
  font-weight: 700;
  letter-spacing: 0.2px;
  box-shadow: 0 8px 20px rgba(10, 0, 20, 0.25);
}

.card {
  background: var(--card);
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid var(--card-border);
  margin: 12px 0 10px 0;
  box-shadow: 0 8px 26px rgba(0, 0, 0, 0.25);
}

.quick-actions-shell {
  margin: 10px 0 12px 0;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(255, 209, 236, 0.35);
  background: linear-gradient(140deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.04));
  box-shadow: 0 10px 26px rgba(10, 0, 20, 0.22);
}

.quick-actions-title {
  color: #ffeaf8;
  font-weight: 700;
  letter-spacing: 0.2px;
}

.quick-actions-sub {
  margin-top: 2px;
  color: #ffd9ee;
  font-size: 0.95rem;
}

.tracker-title {
  margin-top: 0.35rem;
  margin-bottom: 0.25rem;
  font-family: "Sora", sans-serif;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-main);
  letter-spacing: 0.1px;
}

.tracker-meta {
  color: var(--text-soft);
  font-size: 0.95rem;
  margin-bottom: 0.65rem;
}

.tracker-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.65rem;
  margin: 0.6rem 0 0.8rem 0;
}

.tracker-card {
  padding: 12px 13px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.14);
  border-left: 4px solid var(--accent);
  background: linear-gradient(145deg, rgba(255,255,255,0.08), rgba(255,255,255,0.04));
  box-shadow: 0 8px 18px rgba(8, 0, 16, 0.22);
  animation: trackerFadeSlide 0.48s ease both;
}

.tracker-card:nth-child(2) { animation-delay: 0.04s; }
.tracker-card:nth-child(3) { animation-delay: 0.08s; }
.tracker-card:nth-child(4) { animation-delay: 0.12s; }

.tracker-card .label {
  color: var(--text-soft);
  font-size: 0.84rem;
  font-weight: 700;
  letter-spacing: 0.2px;
}

.tracker-card .value {
  margin-top: 5px;
  color: var(--text-main);
  font-size: 1rem;
  font-weight: 700;
  line-height: 1.35;
}

.tracker-timeline-wrap {
  margin-top: 0.25rem;
  border: 1px solid rgba(255,255,255,0.14);
  border-radius: 14px;
  padding: 11px 11px 12px 11px;
  background: linear-gradient(145deg, rgba(255,255,255,0.07), rgba(255,255,255,0.03));
}

.tracker-phase-line {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-soft);
  font-size: 0.92rem;
  margin-bottom: 7px;
}

.tracker-phase-badge {
  border: 1px solid color-mix(in srgb, var(--accent) 60%, white 20%);
  background: color-mix(in srgb, var(--accent) 28%, transparent);
  color: #fff;
  border-radius: 999px;
  padding: 3px 10px;
  font-weight: 700;
}

.tracker-phase-badge.current {
  animation: trackerPulse 1.6s ease-in-out infinite;
}

.tracker-timeline {
  position: relative;
  height: 18px;
  border-radius: 999px;
  background: rgba(255,255,255,0.08);
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.16);
}

.timeline-seg {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 999px;
}

.seg-menstrual { background: rgba(255, 122, 176, 0.58); }
.seg-fertile { background: rgba(90, 224, 155, 0.48); }
.seg-ovulation { background: rgba(255, 209, 87, 0.72); }
.seg-pms { background: rgba(163, 132, 255, 0.5); }

.tracker-marker {
  position: absolute;
  top: -3px;
  width: 3px;
  height: 24px;
  border-radius: 2px;
  background: #ffffff;
  box-shadow: 0 0 10px rgba(255,255,255,0.8);
}

.tracker-legend {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  color: var(--text-soft);
  font-size: 0.82rem;
}

.legend-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  transform: translateY(0.5px);
}

.inline-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border-radius: 999px;
  padding: 5px 11px;
  font-size: 0.84rem;
  font-weight: 700;
  letter-spacing: 0.1px;
  margin: 6px 0 10px 0;
  border: 1px solid rgba(255,255,255,0.2);
}

.chip-success {
  background: rgba(99, 221, 155, 0.15);
  color: #cffff0;
  border-color: rgba(99, 221, 155, 0.38);
}

.chip-info {
  background: rgba(144, 188, 255, 0.14);
  color: #e0eeff;
  border-color: rgba(144, 188, 255, 0.34);
}

.tracker-empty {
  margin-top: 10px;
  border: 1px dashed rgba(255,255,255,0.24);
  border-radius: 14px;
  padding: 14px 14px 12px 14px;
  background: linear-gradient(145deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
}

.tracker-empty-title {
  font-family: "Sora", sans-serif;
  font-weight: 700;
  color: var(--text-main);
  margin-bottom: 4px;
}

.tracker-empty-sub {
  color: var(--text-soft);
  font-size: 0.93rem;
}

@keyframes trackerFadeSlide {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes trackerPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255,255,255,0.0); }
  50% { box-shadow: 0 0 0 6px rgba(255,255,255,0.12); }
}

[data-testid="stExpander"] {
  background: linear-gradient(140deg, var(--bg-2), var(--bg-1));
  border: 1px solid var(--card-border);
  border-radius: 16px;
  box-shadow: 0 8px 22px rgba(11, 2, 22, 0.28);
  overflow: hidden;
}

[data-testid="stExpander"] details {
  background: transparent !important;
}

[data-testid="stExpander"] details summary {
  background: linear-gradient(145deg, var(--bg-2), var(--bg-3)) !important;
  border-bottom: 1px solid var(--card-border);
  min-height: 52px;
}

[data-testid="stExpander"] details summary p {
  font-weight: 700 !important;
  color: #ffeaf8 !important;
}

[data-testid="stExpander"] details[open] summary {
  background: linear-gradient(145deg, var(--bg-3), var(--bg-1)) !important;
}

[data-testid="stExpander"] details summary:hover {
  background: linear-gradient(145deg, var(--bg-2), var(--bg-1)) !important;
}

[data-testid="stExpander"] details summary svg {
  color: #ffeaf8 !important;
  fill: #ffeaf8 !important;
}

[data-testid="stExpander"] details > div {
  background: transparent !important;
}

[data-testid="stExpander"] label,
[data-testid="stExpander"] p,
[data-testid="stExpander"] span {
  color: #ffeaf8 !important;
}

[data-testid="stExpander"] [data-testid="stSlider"] [data-testid="stTickBarMin"],
[data-testid="stExpander"] [data-testid="stSlider"] [data-testid="stTickBarMax"] {
  color: #ffdff4 !important;
}

[data-testid="stExpander"] [data-testid="stSlider"] [data-baseweb="slider"] > div {
  color: #ffb4e6 !important;
}

.stChatMessage {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 210, 240, 0.24);
  border-radius: 14px;
}

.stChatMessage p,
.stChatMessage span {
  color: var(--text-main) !important;
}

.stChatInput input {
  border-radius: 999px !important;
  border: 1px solid rgba(255, 176, 229, 0.45) !important;
  background: rgba(255, 255, 255, 0.09) !important;
  color: var(--text-main) !important;
  width: 100% !important;
}

.stButton button {
  border-radius: 999px;
  border: 1px solid rgba(255, 187, 233, 0.5);
  background: linear-gradient(180deg, #ff82d3, #e95fc0);
  color: white;
  font-weight: 700;
  min-height: 42px;
  transition: all 0.2s ease;
  touch-action: manipulation;
}

.stButton button:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 18px rgba(255, 97, 190, 0.35);
}

.st-key-btn_jordan_message button,
.st-key-btn_study_nudge button,
.st-key-btn_mood_booster button {
  min-height: 48px !important;
  border: 1px solid rgba(255, 217, 242, 0.52) !important;
  box-shadow: 0 8px 18px rgba(255, 94, 188, 0.22);
}

.st-key-btn_jordan_message button {
  background: linear-gradient(180deg, #ffa0db, #f06cc0) !important;
}

.st-key-btn_study_nudge button {
  background: linear-gradient(180deg, #ffb3e3, #f685cf) !important;
}

.st-key-btn_mood_booster button {
  background: linear-gradient(180deg, #ff9fd7, #eb65c0) !important;
}

.st-key-btn_jordan_message button:hover,
.st-key-btn_study_nudge button:hover,
.st-key-btn_mood_booster button:hover {
  transform: translateY(-2px) scale(1.01);
  box-shadow: 0 12px 22px rgba(255, 92, 184, 0.34);
}

@media (max-width: 768px) {
  html, body {
    overflow-x: hidden;
    overscroll-behavior-y: contain;
  }

  div[data-testid="stSidebar"] {
    width: 85vw !important;
    max-width: 320px !important;
  }

  .block-container {
    padding-top: 0.45rem !important;
    padding-left: 0.85rem !important;
    padding-right: 0.85rem !important;
    padding-bottom: calc(5.6rem + var(--safe-bottom)) !important;
  }

  .hero {
    border-radius: 18px;
    padding: 14px 12px 10px 12px;
  }

  .big {
    font-size: clamp(28px, 10vw, 42px);
    line-height: 1.04;
  }

  h2 {
    font-size: clamp(28px, 10.5vw, 48px) !important;
    line-height: 1.1 !important;
    margin: 0.35rem 0 0.6rem 0 !important;
  }

  .sub {
    font-size: 0.98rem;
    line-height: 1.25;
  }

  .whisper {
    margin-top: 8px;
    font-size: 0.98rem;
    line-height: 1.35;
    padding: 10px 11px;
    border-radius: 18px;
  }

  .card {
    margin: 10px 0;
    padding: 12px 13px;
    border-radius: 14px;
    font-size: 1.02rem;
  }

  .stChatMessage {
    border-radius: 13px;
  }

  .stButton button {
    min-height: 46px;
    padding: 0.45rem 1rem;
    font-size: 1rem;
  }

  .stButton > button {
    width: 100% !important;
  }

  [data-testid="stBottomBlockContainer"] {
    padding-bottom: calc(2.9rem + var(--safe-bottom)) !important;
  }

  [data-testid="stChatInput"] {
    padding-left: 0 !important;
    padding-right: 4.9rem !important;
    margin-bottom: calc(2.2rem + var(--safe-bottom)) !important;
  }

  .stChatInput input {
    min-height: 52px !important;
    font-size: 16px !important;
  }

  .stChatMessage {
    padding: 0.2rem 0.1rem;
  }

  div[data-testid="stHorizontalBlock"] {
    gap: 0.45rem !important;
  }

  div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    min-width: 100% !important;
    flex: 1 1 100% !important;
  }
}

@media (max-width: 420px) {
  .block-container {
    padding-left: 0.72rem !important;
    padding-right: 0.72rem !important;
    padding-bottom: calc(5rem + var(--safe-bottom)) !important;
  }

  .hero {
    padding: 12px 10px 9px 10px;
  }

  .big {
    font-size: clamp(24px, 9vw, 34px);
  }

  .sub {
    font-size: 0.92rem;
  }

  .whisper {
    font-size: 0.93rem;
  }

  .card {
    font-size: 0.98rem;
  }

  h2 {
    font-size: clamp(26px, 10.2vw, 38px) !important;
  }

  [data-testid="stChatInput"] {
    padding-right: 4.5rem !important;
    margin-bottom: calc(2rem + var(--safe-bottom)) !important;
  }
}
</style>
""",
    unsafe_allow_html=True,
)

if "ui_theme" not in st.session_state or st.session_state.ui_theme not in THEME_PRESETS:
    st.session_state.ui_theme = "Dreamy"
active_theme = THEME_PRESETS[st.session_state.ui_theme]

st.markdown(
    f"""
<style>
:root {{
  --bg-1: {active_theme["bg_1"]};
  --bg-2: {active_theme["bg_2"]};
  --bg-3: {active_theme["bg_3"]};
  --accent: {active_theme["button_top"]};
  --card-border: {active_theme["card_border"]};
  --text-main: {active_theme["text_main"]};
  --text-soft: {active_theme["text_soft"]};
  --app-bg:
    radial-gradient(circle at 10% 15%, {active_theme["orb_1"]}, transparent 30%),
    radial-gradient(circle at 85% 10%, {active_theme["orb_2"]}, transparent 28%),
    linear-gradient(145deg, var(--bg-1), var(--bg-2) 60%, {active_theme["bg_3"]});
}}

.stButton button {{
  background: linear-gradient(180deg, {active_theme["button_top"]}, {active_theme["button_bottom"]}) !important;
}}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class='hero'>
  <div class='big'>\U0001F497 {BOT_NAME} \U0001F497</div>
  <div class='sub'>a gift from Jordan to his BBG \U0001F380</div>
</div>
<div class='whisper'>My name is Mana, and I am here to answer anything for you.</div>
""",
    unsafe_allow_html=True,
)

with st.expander("\U0001F380 Mana Settings", expanded=False):
    st.caption(f"Theme: {st.session_state.ui_theme}")
    tc1, tc2, tc3, tc4 = st.columns(4)
    if tc1.button("Dreamy", use_container_width=True, key="theme_chip_dreamy"):
        st.session_state.ui_theme = "Dreamy"
        st.rerun()
    if tc2.button("Rose Gold", use_container_width=True, key="theme_chip_rose"):
        st.session_state.ui_theme = "Rose Gold"
        st.rerun()
    if tc3.button("Night Sky", use_container_width=True, key="theme_chip_night"):
        st.session_state.ui_theme = "Night Sky"
        st.rerun()
    if tc4.button("Dark", use_container_width=True, key="theme_chip_dark"):
        st.session_state.ui_theme = "Dark"
        st.rerun()

    playfulness = st.slider("Playfulness", 0, 100, 60, key="playfulness_slider")

with st.expander("\U0001FA78 Period Tracker", expanded=False):
    render_period_tracker()

st.markdown(
    """
<div class='quick-actions-shell'>
  <div class='quick-actions-title'>Quick Actions</div>
  <div class='quick-actions-sub'>Fast boosts generated live by Mana.</div>
</div>
""",
    unsafe_allow_html=True,
)
qa1, qa2, qa3 = st.columns(3)
if qa1.button("\U0001F48C Message From Jordan", use_container_width=True, key="btn_jordan_message"):
    st.toast("Jordan note generated \u2728", icon="\U0001F48C")
    st.success(generate_quick_action_reply("jordan"))
if qa2.button("\U0001F4DA Study Nudge", use_container_width=True, key="btn_study_nudge"):
    st.toast("Study nudge ready", icon="\U0001F4DA")
    st.info(generate_quick_action_reply("study"))
if qa3.button("\U0001F60A Mood Booster", use_container_width=True, key="btn_mood_booster"):
    st.toast("Mood boost ready", icon="\U0001F60A")
    st.success(generate_quick_action_reply("mood"))

today = datetime.datetime.now(IST).date()
next_bday = BDAY.replace(year=today.year)
if next_bday < today:
    next_bday = next_bday.replace(year=today.year + 1)
days = (next_bday - today).days
st.markdown(f"<div class='card'>\U0001F382 Birthday in {days} days \u2022 Taurus \u2649</div>", unsafe_allow_html=True)

period_prediction_main = _predict_period(_load_period_cycles())
if period_prediction_main:
    next_period_date = period_prediction_main["next_start"]
    period_days_left = (next_period_date - today).days
    current_phase = _current_cycle_phase(period_prediction_main, today)
    if period_days_left >= 0:
        period_text = f"\U0001FA78 Next estimated period in {period_days_left} days ({next_period_date.isoformat()})"
    else:
        period_text = f"\U0001FA78 Estimated period was {-period_days_left} days ago ({next_period_date.isoformat()})"
    period_text += f" \u2022 Phase: {current_phase} \u2022 Confidence: {period_prediction_main['confidence']}"
    st.markdown(f"<div class='card'>{period_text}</div>", unsafe_allow_html=True)
else:
    st.markdown(
        "<div class='card'>\U0001FA78 Period estimate unavailable. Add cycle start dates in Period Tracker.</div>",
        unsafe_allow_html=True,
    )

def fact_router(q):
    q = q.lower()
    if "birthday" in q:
        return memory.get("birthday", "22 April 2005") + " \U0001F382"
    if "zodiac" in q:
        return "Taurus \u2649"
    if "pursuing" in q or "study" in q:
        return memory.get("studies", "Law")
    if "likes" in q:
        return ", ".join(memory.get("likes", [])[:5]) or "No likes saved yet. Use `update memory likes to <something>`."
    if "food" in q:
        return ", ".join(memory.get("food_favorites", [])[:3]) or "No food favorites saved yet. Use `update memory food_favorites to <food>`."
    if "goal" in q or "career" in q:
        return memory.get("career_goal", "No career goal saved yet. Use `update memory career_goal to <goal>`.")
    return None


def quick_text_router(q):
    text = q.strip().lower()
    compact = re.sub(r"[^\w\s']", " ", text)
    compact = re.sub(r"\s+", " ", compact).strip()

    if compact in {"hello", "hey", "hi", "hii", "heyy", "yo"}:
        return f"Hey {NAME} \U0001F497 I am here with you."

    if compact in {"how are you", "how r u", "how are u"}:
        return f"I am good, {NAME}. Better because you are here \U0001F497"

    if compact in {"good afternoon", "afternoon"}:
        return f"Good afternoon {NAME} \U0001F497 Keep your pace, you are doing well."

    if compact in {"im tired", "i am tired", "so tired", "tired"}:
        return (
            f"{NAME}, take a tiny pause: water + 3 deep breaths. "
            "I am proud of you for still showing up."
        )

    if compact in {"good night", "gn", "night"}:
        return f"Good night {NAME} \U0001F497 Sleep soft, wake strong."

    if compact in {"good morning", "gm", "morning"}:
        return f"Good morning {NAME} \U0001F497 New day, fresh energy."

    if compact in {"what time should i wake up", "when should i wake up", "wake up time"}:
        wake = memory.get("wake_up_time")
        if wake:
            return f"You should wake up at {wake} \U0001F497"
        return "I do not have your wake-up time yet. Say: `update memory wake_up_time to 7:00 AM`"

    if compact in {"what time should i sleep", "when should i sleep", "sleep time"}:
        sleep = memory.get("sleep_time")
        if sleep:
            return f"Try sleeping by {sleep} for better rest \U0001F497"
        return "I do not have your sleep time yet. Say: `update memory sleep_time to 11:00 PM`"

    if "how is jordan doing" in compact or "how is jordan" in compact:
        return "Thinking about you. Jordan says keep going, you are doing amazing."

    if "thinking about you" in compact:
        return "Always. Jordan is currently thinking about you \U0001F497"

    if "miss you" in compact:
        return f"I know {NAME}. You are deeply loved \U0001F497"

    if "sad" in compact or "low" in compact:
        return f"I am with you {NAME}. One small step right now is enough."

    if "anxious" in compact or "stressed" in compact:
        return "Grounding check: inhale 4 sec, hold 4 sec, exhale 6 sec. Repeat 3 times."

    if compact in {"motivate me", "motivation", "give me motivation"}:
        return f"{NAME}, just start with 10 minutes. Momentum will carry the rest."

    if compact in {"i cant do this", "i can't do this"}:
        return "You can. Make it smaller: one tiny step now, next step after."

    if compact in {"thank you", "thanks", "ty"}:
        return f"Always for you, {NAME} \U0001F497"

    return None


def normalize_birthday(value):
    raw = str(value).strip()
    for parser in (
        lambda x: datetime.date.fromisoformat(x),
        lambda x: datetime.datetime.strptime(x, "%d %B %Y").date(),
        lambda x: datetime.datetime.strptime(x, "%d %b %Y").date(),
        lambda x: datetime.datetime.strptime(x, "%d-%m-%Y").date(),
        lambda x: datetime.datetime.strptime(x, "%d/%m/%Y").date(),
    ):
        try:
            return parser(raw).isoformat()
        except Exception:
            pass
    return None


def _first_list_item(key, fallback):
    value = memory.get(key, [])
    if isinstance(value, list) and value:
        return str(value[0])
    return fallback


def _store_spark_reply(prompt, reply):
    reply_text = str(reply).strip()
    if "manasyee" not in reply_text.lower():
        reply_text = f"Manasyee, {reply_text}"
    bank = st.session_state.setdefault("spark_reply_bank", {})
    bank[prompt.strip()] = reply_text
    if len(bank) > 80:
        keys = list(bank.keys())
        for k in keys[:-80]:
            bank.pop(k, None)


def spark_direct_reply(query):
    bank = st.session_state.get("spark_reply_bank", {})
    if not isinstance(bank, dict):
        return None
    return bank.get(str(query).strip())


def generate_prompt_spark():
    now = datetime.datetime.now(IST)
    hour = now.hour
    studies = str(memory.get("studies", "your studies")).strip() or "your studies"
    goal = str(memory.get("career_goal", "your goal")).strip() or "your goal"
    favorite = _first_list_item("likes", "one thing I love")
    artist = _first_list_item("music_artists", "a song I like")
    food = _first_list_item("food_favorites", "something comforting to eat")

    recent_user = " ".join(
        str(m.get("content", "")).lower() for m in st.session_state.get("msgs", [])[-8:] if m.get("role") == "user"
    )
    candidates = [
        (
            f"Give me a 20-minute action plan to get closer to {goal} today.",
            "20-min sprint: 1) 5 min plan one micro-task, 2) 10 min deep work no phone, 3) 5 min recap + next step.",
        ),
        (
            f"Ask me 3 reflective questions that can help me stay focused on {studies}.",
            f"3 questions: Why does {studies} matter to me now? What one task gives biggest progress today? What distraction will I block first?",
        ),
        (
            "Give me a tiny reset routine (2 minutes) when I feel overwhelmed.",
            "2-min reset: inhale 4s, hold 4s, exhale 6s x5; sip water; do one tiny task for 60 seconds.",
        ),
        (
            f"Help me turn '{favorite}' into a reward-based study routine.",
            f"Use '{favorite}' as reward: 25 min focus, 5 min reward. Repeat 3 rounds, then longer break.",
        ),
        (
            f"Give me a calm bedtime wind-down routine with {artist} vibes.",
            f"Wind-down: dim lights, play {artist}, 5 deep breaths, write 3 wins, set tomorrow's top task, then sleep.",
        ),
        (
            f"Plan a cozy self-care evening with {food} as the reward.",
            f"Self-care plan: quick shower, 15 min tidy, 20 min gentle study, then enjoy {food} guilt-free.",
        ),
        (
            "Ask me one deep question about my future self, then help me answer it.",
            "Deep Q: 'What would future me thank me for tonight?' Answer in 1 line, then do one action that proves it.",
        ),
        (
            "Give me one sweet motivation line and one practical next step.",
            "You are loved and capable. Next step: start a 10-minute timer and complete just the first small task.",
        ),
    ]

    if 5 <= hour < 12:
        candidates.extend(
            [
                (
                    f"Create a simple morning routine for me in IST to focus on {studies}.",
                    f"Morning IST: hydrate, 20 min {studies} revision, 10 min summary notes, then start your first priority task.",
                ),
                (
                    "Give me a 3-task priority list for this morning and the order to do it.",
                    "Priority order: 1) hardest task first, 2) medium task, 3) easy admin task. Start now with 15 focused minutes.",
                ),
            ]
        )
    elif 12 <= hour < 18:
        candidates.extend(
            [
                (
                    f"Build a no-overthinking afternoon plan to make progress on {goal}.",
                    "Afternoon plan: pick one outcome, set 25-minute timer, finish draft, then 5-minute break and repeat once.",
                ),
                (
                    "I am losing momentum. Give me a 15-minute comeback plan.",
                    "15-min comeback: 2 min breathe + clear desk, 10 min single task sprint, 3 min quick review and next action.",
                ),
            ]
        )
    else:
        candidates.extend(
            [
                (
                    "Give me a gentle evening check-in: what I did well and what to do tomorrow.",
                    "Tonight: list 2 wins, 1 lesson, and 1 top task for tomorrow. Keep it kind, not perfect.",
                ),
                (
                    "Write a short night affirmation and one realistic target for tomorrow.",
                    "Affirmation: 'I am improving daily with calm consistency.' Tomorrow target: one 25-minute focused block before noon.",
                ),
            ]
        )

    if any(x in recent_user for x in ["sad", "low", "anxious", "stressed", "tired"]):
        candidates.extend(
            [
                (
                    "I feel low. Give me a grounding script and one tiny action I can do now.",
                    "Grounding: name 5 things you see, 4 you feel, 3 you hear. Tiny action now: drink water and stretch for 60 seconds.",
                ),
                (
                    "Give me a comforting message plus one gentle plan for the next 30 minutes.",
                    "You are safe and not behind. Next 30 min: 10 min rest, 15 min one easy task, 5 min reset.",
                ),
            ]
        )

    if not memory.get("likes"):
        candidates.append(
            (
                "Ask me about 3 things I like so we can store them in memory.",
                "Tell me 3 things you like and I will save them. Format: `update memory likes to <thing>`.",
            )
        )
    if not memory.get("music_artists"):
        candidates.append(
            (
                "Ask me my top 3 music artists and save them to memory.",
                "Share your top 3 artists and I will store them. Format: `update memory music_artists to <artist>`.",
            )
        )
    if not memory.get("food_favorites"):
        candidates.append(
            (
                "Ask me my comfort foods and save them in memory.",
                "Tell me your comfort foods and I will save them. Format: `update memory food_favorites to <food>`.",
            )
        )

    recent_sparks = st.session_state.setdefault("spark_recent", [])
    pool = [item for item in candidates if item[0] not in recent_sparks] or candidates
    choice_prompt, choice_reply = random.choice(pool)
    recent_sparks.append(choice_prompt)
    if len(recent_sparks) > 12:
        del recent_sparks[:-12]
    _store_spark_reply(choice_prompt, choice_reply)
    return choice_prompt


def smart_memory_answer(query):
    q_tokens = set(normalize_tokens(query))
    if not q_tokens:
        return None

    index = get_cached_memory_index()
    best = None
    best_score = 0

    for item in index:
        key_overlap = len(q_tokens & item["key_tokens"])
        value_overlap = len(q_tokens & item["value_tokens"])
        score = (2.5 * key_overlap) + (1.0 * value_overlap)

        if key_overlap > 0 and value_overlap == 0:
            score += 0.5
        if score > best_score:
            best_score = score
            best = item

    if not best or best_score < 1.5:
        return None

    if isinstance(memory.get(best["key"]), list):
        return f"{best['pretty_key'].title()}: {', '.join(memory.get(best['key'], [])[:7])}"
    return f"{best['pretty_key'].title()}: {memory.get(best['key'])}"


def build_relevant_memory_context(query, max_items=6):
    q_tokens = set(normalize_tokens(query))
    if not q_tokens:
        return ""

    ranked = []
    for item in get_cached_memory_index():
        key_overlap = len(q_tokens & item["key_tokens"])
        value_overlap = len(q_tokens & item["value_tokens"])
        score = (2.5 * key_overlap) + (1.0 * value_overlap)
        if score <= 0:
            continue
        ranked.append((score, item))

    ranked.sort(key=lambda x: x[0], reverse=True)
    picked = ranked[:max_items]
    if not picked:
        return ""

    lines = []
    seen = set()
    for _, item in picked:
        key = item.get("key", "")
        text = item.get("text", "")
        key_text = f"{key}: {text}".strip()
        if key_text in seen:
            continue
        seen.add(key_text)
        lines.append(f"- {key_text}")
    if not lines:
        return ""

    return "Relevant memory for this query:\n" + "\n".join(lines)


def process_memory_command(text):
    raw = text.strip()
    lower = raw.lower()
    memory_store.reload_if_changed()

    if lower.startswith("remember ") and not lower.startswith("remember this"):
        return "Use `remember this <text>`. Example: `remember this i like gintama`."

    if lower.startswith("update memory") and " to " not in lower:
        return "Use `update memory <field> to <value>`. Example: `update memory likes to gintama`."

    if lower.startswith("delete memory") and not re.match(
        r"^(delete memory\s+[\w_]+|delete memory\s+[\w_]+\s*:\s*.+)$",
        raw,
        flags=re.IGNORECASE,
    ):
        return (
            "Use `delete memory <field>` or `delete memory <list_field>:<item>`."
        )

    confirm_delete_match = re.match(r"^confirm delete memory\s+([\w_]+)$", raw, flags=re.IGNORECASE)
    if confirm_delete_match:
        key = confirm_delete_match.group(1).strip()
        pending = st.session_state.get("pending_delete_memory_key")
        if pending != key:
            return f"No pending delete for `{key}`. Use `delete memory {key}` first."
        if key not in memory:
            st.session_state.pop("pending_delete_memory_key", None)
            return f"`{key}` was not found in memory."
        result = memory_store.delete_key(key, updated_by="user")
        st.session_state.pop("pending_delete_memory_key", None)
        if not result["ok"]:
            return f"Could not delete `{key}`."
        invalidate_memory_caches()
        return f"Deleted memory field `{key}`."

    if lower.startswith("remember this"):
        item = re.sub(r"^remember this[:\-\s]*", "", raw, flags=re.IGNORECASE).strip()
        if not item:
            return "Tell me what to remember after `remember this`."
        result = memory_store.append_unique("notes", item, updated_by="user")
        if not result["ok"] and result["message"] == "duplicate":
            return "That note already exists in memory."
        if not result["ok"]:
            return "Could not save that note right now."
        invalidate_memory_caches()
        return f"Saved in memory: {item}"

    update_match = re.match(r"^(force\s+)?update memory\s+([\w_]+)\s+to\s+(.+)$", raw, flags=re.IGNORECASE)
    if update_match:
        force_update = bool(update_match.group(1))
        key = update_match.group(2).strip()
        value = update_match.group(3).strip()
        if not value:
            return "Please provide a value to update."

        # Validate known date fields and normalize to ISO for consistency.
        if key in {"birthday"}:
            normalized = normalize_birthday(value)
            if not normalized:
                return "Invalid date format. Try `22 April 2005` or `2005-04-22`."
            value = normalized
            current = str(memory.get(key, "")).strip()
            if current and current != value and not force_update:
                return (
                    f"`{key}` already has `{current}`. "
                    f"Use `force update memory {key} to {value}` to overwrite."
                )

        if isinstance(memory.get(key), list):
            result = memory_store.append_unique(key, value, updated_by="user")
            if not result["ok"] and result["message"] == "duplicate":
                return f"`{value}` already exists in `{key}`."
            if not result["ok"]:
                return f"Could not update `{key}` right now."
            invalidate_memory_caches()
            return f"Added to `{key}`."

        current = str(memory.get(key, "")).strip()
        if current and current != value and not force_update and key in {"name", "preferred_name", "recipient_name"}:
            return (
                f"`{key}` already has `{current}`. "
                f"Use `force update memory {key} to {value}` to overwrite."
            )
        result = memory_store.set(key, value, updated_by="user")
        if not result["ok"]:
            return f"Could not update `{key}` right now."
        invalidate_memory_caches()
        return f"Updated `{key}`."

    delete_value_match = re.match(r"^delete memory\s+([\w_]+)\s*:\s*(.+)$", raw, flags=re.IGNORECASE)
    if delete_value_match:
        key = delete_value_match.group(1).strip()
        value = delete_value_match.group(2).strip()
        if key not in memory:
            return f"`{key}` was not found in memory."
        if not isinstance(memory[key], list):
            return f"`{key}` is not a list. Use `delete memory {key}`."
        result = memory_store.delete_from_list(key, value, updated_by="user")
        if not result["ok"] and result["message"] == "item_missing":
            return f"`{value}` was not found in `{key}`."
        if not result["ok"]:
            return f"Could not delete from `{key}` right now."
        invalidate_memory_caches()
        return f"Deleted `{value}` from `{key}`."

    delete_key_match = re.match(r"^delete memory\s+([\w_]+)$", raw, flags=re.IGNORECASE)
    if delete_key_match:
        key = delete_key_match.group(1).strip()
        if key not in memory:
            return f"`{key}` was not found in memory."
        st.session_state["pending_delete_memory_key"] = key
        return f"Type `confirm delete memory {key}` to delete this field."

    help_patterns = ["help memory", "memory help", "how to update memory", "how to delete memory"]
    if lower in help_patterns:
        return (
            "Memory commands:\n"
            "1) remember this <text>\n"
            "2) update memory <field> to <value>\n"
            "3) force update memory <field> to <value>\n"
            "4) delete memory <field>\n"
            "5) confirm delete memory <field>\n"
            "6) delete memory <list_field>:<item>\n"
            "Examples:\n"
            "- remember this i like gintama\n"
            "- update memory likes to gintama\n"
            "- delete memory likes:gintama"
        )

    return None


def generation_settings(playfulness_value):
    ratio = max(0.0, min(1.0, float(playfulness_value) / 100.0))
    temperature = round(0.05 + (ratio * 0.95), 2)
    top_p = round(0.75 + (ratio * 0.25), 2)
    return temperature, top_p


def build_recent_conversation_messages(limit_messages=8):
    raw_msgs = st.session_state.get("msgs", [])
    if not isinstance(raw_msgs, list):
        return []

    # Current user message is already passed separately as user_text.
    if raw_msgs and isinstance(raw_msgs[-1], dict) and raw_msgs[-1].get("role") == "user":
        history = raw_msgs[:-1]
    else:
        history = raw_msgs

    conversation = []
    for item in history[-limit_messages:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            conversation.append({"role": role, "content": content})
    return conversation


def openrouter_chat(system_prompt, user_text, playfulness_value, conversation_history=None):
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENROUTER_API_KEY (or OPENAI_API_KEY).")
    if not OPENAI_BASE_URL:
        raise RuntimeError("Missing OPENAI_BASE_URL.")

    url = f"{OPENAI_BASE_URL}/chat/completions"
    temperature, top_p = generation_settings(playfulness_value)
    messages = [{"role": "system", "content": system_prompt}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_text})
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL
    if OPENROUTER_APP_NAME:
        headers["X-Title"] = OPENROUTER_APP_NAME

    def _send_once(messages_payload):
        req_payload = dict(payload)
        req_payload["messages"] = messages_payload
        req = urllib.request.Request(url, data=json.dumps(req_payload).encode("utf-8"), method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no choices.")

        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        finish_reason = str(first.get("finish_reason", "unknown"))

        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text_piece = item.get("text")
                    if isinstance(text_piece, str) and text_piece.strip():
                        parts.append(text_piece.strip())
            text = " ".join(parts).strip()
        else:
            alt_text = first.get("text")
            text = alt_text.strip() if isinstance(alt_text, str) else ""

        return text, finish_reason

    full_text_parts = []
    current_messages = list(messages)
    max_continues = max(0, OPENROUTER_MAX_AUTO_CONTINUES)

    for _ in range(max_continues + 1):
        chunk, finish_reason = _send_once(current_messages)
        if chunk:
            full_text_parts.append(chunk)
        if finish_reason not in {"length", "max_tokens"}:
            break

        # Ask for seamless continuation when provider cuts off output.
        continuation_seed = "\n\n".join(full_text_parts).strip()
        current_messages = current_messages + [
            {"role": "assistant", "content": continuation_seed},
            {
                "role": "user",
                "content": "Continue exactly from where you stopped. Do not restart or summarize.",
            },
        ]

    final_text = "\n\n".join([p for p in full_text_parts if p]).strip()
    if final_text:
        return final_text
    raise RuntimeError(f"Model returned empty content (finish_reason={finish_reason}).")


def ai_reply(text):
    system_prompt = get_cached_memory_prompt(playfulness)
    memory_context = build_relevant_memory_context(text)
    conversation_history = build_recent_conversation_messages(limit_messages=8)
    if memory_context:
        user_text = f"{text}\n\n{memory_context}"
    else:
        user_text = text
    try:
        return openrouter_chat(system_prompt, user_text, playfulness, conversation_history=conversation_history)
    except urllib.error.HTTPError as e:
        details = ""
        try:
            raw = e.read().decode("utf-8", errors="ignore")
            parsed = json.loads(raw) if raw else {}
            details = parsed.get("error", {}).get("message") or parsed.get("message") or ""
        except Exception:
            details = ""
        if e.code == 429:
            return f"OpenRouter rate limit hit (429). {details or 'Please retry in a bit.'}"
        if e.code in {401, 403}:
            return f"OpenRouter auth failed ({e.code}). {details or 'Check OPENROUTER_API_KEY/OPENAI_API_KEY.'}"
        return f"OpenRouter API error ({e.code}). {details or 'Please try again shortly.'}"
    except urllib.error.URLError as e:
        return f"Network error reaching OpenRouter: {getattr(e, 'reason', e)}"
    except RuntimeError as e:
        return str(e)
    except Exception:
        return (
            "I cannot reach the model right now. "
            "Set `OPENROUTER_API_KEY` (or `OPENAI_API_KEY`) and optionally `OPENAI_BASE_URL` for OpenRouter."
        )


def _is_model_error_message(text):
    if not isinstance(text, str):
        return True
    lowered = text.strip().lower()
    if not lowered:
        return True
    error_markers = (
        "missing openrouter_api_key",
        "missing openai_api_key",
        "missing openai_base_url",
        "openrouter rate limit hit",
        "openrouter auth failed",
        "openrouter api error",
        "network error reaching openrouter",
        "i cannot reach the model right now",
        "model returned empty content",
        "openrouter returned no choices",
    )
    return any(marker in lowered for marker in error_markers)


if "msgs" not in st.session_state:
    st.session_state.msgs = []

for m in st.session_state.msgs:
    with st.chat_message(m["role"], avatar="\U0001F478" if m["role"] == "user" else "\U0001F431"):
        st.write(m["content"])

chat_tools_space, clear_btn_col, spark_btn_col = st.columns([9.2, 0.8, 0.8])
with chat_tools_space:
    st.write("")
with clear_btn_col:
    if st.button("\U0001F9F9", key="clear_chat_btn", help="Clear chat"):
        st.session_state.msgs = []
        st.session_state.pop("queued_user_input", None)
        st.rerun()
with spark_btn_col:
    if st.button("\u2728", key="prompt_spark_btn", help="Generate a smart prompt"):
        st.session_state["queued_user_input"] = generate_prompt_spark()
        st.rerun()

queued_user = st.session_state.pop("queued_user_input", None)
typed_user = st.chat_input("Talk to Mana...", key="chat_input_box")
user = typed_user or queued_user

if user:
    memory_store.reload_if_changed()
    st.session_state.msgs.append({"role": "user", "content": user})
    with st.chat_message("user", avatar="\U0001F478"):
        st.write(user)

    with st.chat_message("assistant", avatar="\U0001F431"):
        thinking_slot = st.empty()
        thinking_slot.markdown("Mana is thinking...")

        direct_spark = spark_direct_reply(user)
        command_reply = process_memory_command(user)
        if direct_spark:
            reply = direct_spark
        elif command_reply:
            reply = command_reply
        else:
            llm_reply = ai_reply(user)
            if _is_model_error_message(llm_reply):
                reply = quick_text_router(user) or fact_router(user) or smart_memory_answer(user) or llm_reply
            else:
                reply = llm_reply

        thinking_slot.empty()
        st.write(reply)            
    st.session_state.msgs.append({"role": "assistant", "content": reply})


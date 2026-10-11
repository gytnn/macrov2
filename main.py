# -*- coding: utf-8 -*-
"""
VVIP PUBG - App macro giảm giật (pywebview) + KeyAuth License System.

Tab 1: Thông tin máy
Tab 2: 2 ô súng + phụ kiện -> tự tính độ giật -> engine kéo chuột.
"""

import json
import os
import sys
import threading

import webview

try:
    import cv2
except Exception:
    cv2 = None

from keyauth import api  # KeyAuth kütüphanesi

from backend import weapons
from backend import vision
from backend.system_info import get_system_info, get_live_stats
from backend.recoil_engine import EngineState, RecoilEngine
from backend.vision import WeaponDetector
from backend.detection import DetectionController
from backend.overlay import Overlay

# ================= KEYAUTH AYARLARI =================
KEYAUTH_NAME = "Mevlutmix's Application"
KEYAUTH_OWNERID = "gl5QIjijri"
KEYAUTH_SECRET = "72d5b2d9a64a8ffe5c23bdc120e9f3c37896a63cf64ff871de16202c802d69ec"  # Paneldeki Gizli Anahtar (Secret) buraya yazılacak
KEYAUTH_VERSION = "1.0"

# KeyAuth nesnesini başlatma
keyauthapp = api(
    name=KEYAUTH_NAME,
    ownerid=KEYAUTH_OWNERID,
    secret=KEYAUTH_SECRET,
    version=KEYAUTH_VERSION
)
# ====================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# PyInstaller uyumlu yol yönetimi
if getattr(sys, 'frozen', False):
    FROZEN_BASE = sys._MEIPASS
    EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    FROZEN_BASE = BASE_DIR
    EXE_DIR = BASE_DIR

WEB_DIR = os.path.join(FROZEN_BASE, "web")
CONFIG_PATH = os.path.join(EXE_DIR, "config.json")
SHOT_PATH = os.path.join(EXE_DIR, "shot.png")   # ảnh test có sẵn

# Phím nóng có thể chọn trong Tab Cài đặt: (nhãn hiển thị, VK code)
KEY_OPTIONS = [
    {"name": "1", "vk": 0x31}, {"name": "2", "vk": 0x32},
    {"name": "3", "vk": 0x33}, {"name": "4", "vk": 0x34},
    {"name": "5", "vk": 0x35},
    {"name": "Q", "vk": 0x51}, {"name": "E", "vk": 0x45},
    {"name": "F", "vk": 0x46}, {"name": "C", "vk": 0x43},
    {"name": "V", "vk": 0x56}, {"name": "X", "vk": 0x58},
    {"name": "Tab", "vk": 0x09}, {"name": "CapsLock", "vk": 0x14},
    {"name": "F1", "vk": 0x70}, {"name": "F2", "vk": 0x71},
    {"name": "F3", "vk": 0x72}, {"name": "F4", "vk": 0x73},
    {"name": "F8", "vk": 0x77}, {"name": "F9", "vk": 0x78},
    {"name": "F10", "vk": 0x79}, {"name": "F11", "vk": 0x7A},
    {"name": "F12", "vk": 0x7B}, {"name": "Insert", "vk": 0x2D}, {"name": "Del", "vk": 0x2E},
    {"name": "Home", "vk": 0x24}, {"name": "End", "vk": 0x23},
]

DEFAULT_SLOT_CONFIG = lambda: [
    {"weapon_id": None, "attachments": {"scope": "none", "muzzle": "none", "grip": "none", "stock": "none", "mag": "none"}},
    {"weapon_id": None, "attachments": {"scope": "none", "muzzle": "none", "grip": "none", "stock": "none", "mag": "none"}},
]


class Api:
    def __init__(self):
        self.state = EngineState()
        self.engine = RecoilEngine(self.state)
        self.sensitivity = 1.0
        self.slot_config = DEFAULT_SLOT_CONFIG()
        self.weapon_overrides = {}
        self.attachment_overrides = {}
        self._rebuild_data()

        self.match_thresholds = {}
        self.detector = WeaponDetector()
        self.controller = DetectionController(self.detector, self.apply_detection)
        self.engine.on_detect = self.controller.trigger
        self.engine.on_show_boxes = self.show_attach_boxes
        self._boxes_busy = False
        self._detect_version = 0
        self._detect_last = {"slots": [None, None], "texts": ["", ""], "test_mode": False}

        self.overlay = Overlay(self.get_overlay_data, self.save_boxes)

        self._load_config()
        self.controller.start()

    def _rebuild_data(self):
        self._weapons = []
        for w in weapons.WEAPONS:
            w2 = dict(w)
            ov = self.weapon_overrides.get(w["id"])
            if ov:
                if "rpm" in ov:
                    w2["rpm"] = ov["rpm"]
                if "recoil_phases" in ov:
                    w2["recoil_phases"] = list(ov["recoil_phases"])
            self._weapons.append(w2)
        self._weapon_by_id = {w["id"]: w for w in self._weapons}

        self._attachments = {}
        for cat, items in weapons.ATTACHMENTS.items():
            lst = []
            for a in items:
                a2 = dict(a)
                ov = self.attachment_overrides.get(f"{cat}:{a['id']}")
                if ov and "vert" in ov:
                    a2["vert"] = ov["vert"]
                lst.append(a2)
            self._attachments[cat] = lst

    def get_weapons(self):
        return self._weapons

    def get_attachments(self):
        return self._attachments

    def get_allowed_attachments(self, weapon_id):
        w = self._weapon_by_id.get(weapon_id)
        return {
            cat: weapons.allowed_attachments(w, cat, self._attachments)
            for cat in weapons.ATTACH_CATEGORIES
        }

    def get_key_options(self):
        return KEY_OPTIONS

    def get_system_info(self):
        return get_system_info()

    def get_live_stats(self):
        return get_live_stats()

    def get_config(self):
        snap = self.state.snapshot()
        return {
            "sensitivity": self.sensitivity,
            "enabled": snap["enabled"],
            "require_ads": snap["require_ads"],
            "hipfire_mult": snap["hipfire_mult"],
            "active_slot": snap["active_slot"],
            "vk_slot1": snap["vk_slot1"],
            "vk_slot2": snap["vk_slot2"],
            "vk_toggle": snap["vk_toggle"],
            "vk_overlay": snap["vk_overlay"],
            "vk_boxes": snap["vk_boxes"],
            "ccw_enabled": snap["ccw_enabled"],
            "ccw_cooldown": snap["ccw_cooldown"],
            "auto_detect": snap["auto_detect"],
            "auto_draft_icons": self.detector.auto_draft,
            "overlay_visible": snap["overlay_visible"],
            "test_mode": bool(self.detector.debug_image),
            "has_shot": os.path.exists(SHOT_PATH),
            "slot_config": self.slot_config,
            "profiles": [self._profile_for(i) for i in range(2)],
        }

    def _profile_for(self, idx):
        cfg = self.slot_config[idx]
        if not cfg["weapon_id"]:
            return None
        w = self._weapon_by_id.get(cfg["weapon_id"])
        return weapons.compute_profile(w, cfg["attachments"], self._attachments, self.sensitivity)

    def _apply_slot(self, idx):
        prof = self._profile_for(idx)
        with self.state.lock:
            if prof:
                pulls = (
                    [0.0] * len(prof["phases"])
                    if prof.get("type") == "SR"
                    else [ph["pull_per_sec"] for ph in prof["phases"]]
                )
                self.state.slots[idx] = {
                    "name": prof["weapon_name"],
                    "shots_per_sec": prof["shots_per_sec"],
                    "phase_pulls": pulls,
                    "phase_bounds": prof["phase_bounds"],
                }
            else:
                self.state.slots[idx] = None

    def update_slot(self, idx, weapon_id, attachments):
        idx = int(idx)
        self.slot_config[idx]["weapon_id"] = weapon_id or None
        if attachments:
            self.slot_config[idx]["attachments"] = weapons.sanitize_attachments(
                weapon_id, attachments)
        self._apply_slot(idx)
        self._save_config()
        return self._profile_for(idx)

    def set_sensitivity(self, value):
        self.sensitivity = max(0.05, float(value))
        self._apply_slot(0)
        self._apply_slot(1)
        self._save_config()
        return [self._profile_for(0), self._profile_for(1)]

    def set_enabled(self, value):
        with self.state.lock:
            self.state.enabled = bool(value)
        self._save_config()
        return self.state.enabled

    def set_require_ads(self, value):
        with self.state.lock:
            self.state.require_ads = bool(value)
        self._save_config()
        return self.state.require_ads

    def update_weapon(self, weapon_id, rpm, phases):
        w = self._weapon_by_id.get(weapon_id)
        if w and w.get("type") == "SR":
            return [self._profile_for(0), self._profile_for(1)]
        self.weapon_overrides[weapon_id] = {
            "rpm": max(1.0, float(rpm)),
            "recoil_phases": [max(0.0, float(x)) for x in phases],
        }
        self._rebuild_data()
        self._apply_slot(0)
        self._apply_slot(1)
        self._save_config()
        return [self._profile_for(0), self._profile_for(1)]

    def update_attachment(self, cat, att_id, vert):
        self.attachment_overrides[f"{cat}:{att_id}"] = {
            "vert": max(0.0, float(vert)),
        }
        self._rebuild_data()
        self._apply_slot(0)
        self._apply_slot(1)
        self._save_config()
        return [self._profile_for(0), self._profile_for(1)]

    def set_hipfire_mult(self, value):
        v = max(0.0, min(1.0, float(value)))
        with self.state.lock:
            self.state.hipfire_mult = v
        self._save_config()
        return v

    def set_hotkeys(self, vk_slot1, vk_slot2, vk_toggle, vk_overlay=None, vk_boxes=None):
        with self.state.lock:
            self.state.vk_slot1 = int(vk_slot1)
            self.state.vk_slot2 = int(vk_slot2)
            self.state.vk_toggle = int(vk_toggle)
            if vk_overlay is not None:
                self.state.vk_overlay = int(vk_overlay)
            if vk_boxes is not None:
                self.state.vk_boxes = int(vk_boxes)
        self._save_config()
        return True

    def set_ccw_enabled(self, value):
        with self.state.lock:
            self.state.ccw_enabled = bool(value)
        self._save_config()
        return self.state.ccw_enabled

    def set_ccw_cooldown(self, value):
        v = max(0.5, min(15.0, float(value)))
        with self.state.lock:
            self.state.ccw_cooldown = v
        self._save_config()
        return v

    def get_overlay_data(self):
        snap = self.state.snapshot()
        slots = []
        for i in range(2):
            cfg = self.slot_config[i]
            wid = cfg.get("weapon_id")
            if not wid:
                slots.append(None)
                continue
            w = self._weapon_by_id.get(wid)
            atts = cfg.get("attachments") or {}
            names = []
            for cat in weapons.ATTACH_CATEGORIES:
                aid = atts.get(cat, "none")
                if aid and aid != "none":
                    a = next((x for x in self._attachments.get(cat, []) if x["id"] == aid), None)
                    names.append(a["name"] if a else aid)
            prof = self._profile_for(i)
            slots.append({
                "name": w["name"] if w else wid,
                "type": w["type"] if w else "",
                "atts": names,
                "mult": prof["mult"] if prof else 1.0,
            })
        return {
            "visible": snap["overlay_visible"],
            "enabled": snap["enabled"],
            "active_slot": snap["active_slot"],
            "sensitivity": self.sensitivity,
            "slots": slots,
            "debug_visible": snap.get("debug_boxes_visible", False),
            "boxes": self._debug_boxes(),
        }

    def _debug_boxes(self):
        boxes = []
        for rkey, label in (("slot1_name", "Tên 1"), ("slot2_name", "Tên 2")):
            r = self.detector.regions.get(rkey)
            if r:
                x, y, w, h = r
                boxes.append({"key": f"name:{rkey}", "x": x, "y": y, "w": w, "h": h, "label": label, "kind": "name"})
        labels = getattr(WeaponDetector, "BOX_LABELS", ["scope", "muzzle", "grip", "stock"])
        for slot in (0, 1):
            for idx, box in enumerate(self.detector.attach_slots.get(slot, [])):
                x, y, w, h = box
                kind = labels[idx] if idx < len(labels) else f"#{idx}"
                boxes.append({"key": f"att:{slot}:{idx}", "x": x, "y": y, "w": w, "h": h, "label": f"{slot + 1}·{kind}", "kind": kind})
        return boxes

    def save_boxes(self, boxes):
        regions = {k: list(v) for k, v in self.detector.regions.items()}
        slots = {s: [list(b) for b in self.detector.attach_slots.get(s, [])] for s in (0, 1)}
        for b in boxes or []:
            key = str(b.get("key", ""))
            rect = [int(b.get("x", 0)), int(b.get("y", 0)), int(b.get("w", 0)), int(b.get("h", 0))]
            if key.startswith("name:"):
                regions[key.split(":", 1)[1]] = rect
            elif key.startswith("att:"):
                _, s, i = key.split(":")
                s, i = int(s), int(i)
                if s in slots and 0 <= i < len(slots[s]):
                    slots[s][i] = rect
        self.detector.regions = regions
        self.detector.set_attach_slots(slots)
        self._save_config()
        return True

    def toggle_overlay(self):
        with self.state.lock:
            self.state.overlay_visible = not self.state.overlay_visible
            return self.state.overlay_visible

    def set_overlay(self, value):
        with self.state.lock:
            self.state.overlay_visible = bool(value)
            return self.state.overlay_visible

    def reset_config(self):
        self.sensitivity = 1.0
        self.slot_config = DEFAULT_SLOT_CONFIG()
        self.weapon_overrides = {}
        self.attachment_overrides = {}
        self._rebuild_data()
        with self.state.lock:
            self.state.require_ads = True
            self.state.hipfire_mult = 0.5
            self.state.vk_slot1 = 0x31
            self.state.vk_slot2 = 0x32
            self.state.vk_toggle = 0x77
            self.state.vk_overlay = 0x2E
            self.state.vk_boxes = 0x79
            self.state.enabled = True
            self.state.auto_detect = False
            self.state.overlay_visible = False
            self.state.ccw_enabled = False
            self.state.ccw_cooldown = 2.0
        self.detector.debug_image = None
        self._apply_slot(0)
        self._apply_slot(1)
        self._save_config()
        return self.get_config()

    def save_now(self):
        self._save_config()
        return True

    def set_active_slot(self, idx):
        with self.state.lock:
            self.state.active_slot = int(idx)
        return self.state.active_slot

    def get_status(self):
        snap = self.state.snapshot()
        snap["detect_version"] = self._detect_version
        snap["detect_last"] = self._detect_last
        return snap

    def apply_detection(self, result):
        if not result.get("inventory_open"):
            return False
        slots = [None, None]
        texts = ["", ""]
        atts_out = [None, None]
        applied = False
        for slot in (0, 1):
            r = result.get(slot, {})
            texts[slot] = r.get("text", "")
            wid = r.get("weapon_id")
            if wid:
                applied = True
                slots[slot] = wid
                atts = r.get("attachments") or self.slot_config[slot]["attachments"]
                atts_out[slot] = atts
                self.update_slot(slot, wid, atts)
        self._detect_version += 1
        self._detect_last = {
            "slots": slots,
            "texts": texts,
            "attachments": atts_out,
            "inventory_open": True,
            "test_mode": bool(self.detector.debug_image),
        }
        return applied

    def detect_now(self):
        try:
            self.controller.detect_once()
        except Exception as e:
            self._detect_last = {"slots": [None, None], "texts": [str(e), ""], "test_mode": bool(self.detector.debug_image)}
            self._detect_version += 1
        return self._detect_last

    def show_attach_boxes(self):
        if self._boxes_busy:
            return False
        self._boxes_busy = True

        def _work():
            try:
                if cv2 is None:
                    return
                img = self.detector.capture()
                vis = self.detector.annotate_boxes(img)
                if vis is None:
                    return
                out_dir = os.path.join(EXE_DIR, "debug")
                os.makedirs(out_dir, exist_ok=True)
                path = os.path.join(out_dir, "attach_boxes.png")
                cv2.imwrite(path, vis)
                try:
                    os.startfile(path)
                except Exception:
                    pass
            except Exception:
                pass
            finally:
                self._boxes_busy = False

        threading.Thread(target=_work, daemon=True).start()
        return True

    def set_auto_detect(self, value):
        with self.state.lock:
            self.state.auto_detect = bool(value)
        if not value:
            self.controller.reset_tab_cycle()
        self._save_config()
        return self.state.auto_detect

    def set_auto_draft_icons(self, value):
        self.detector.auto_draft = bool(value)
        self._save_config()
        return self.detector.auto_draft

    def set_match_threshold(self, cat, value):
        self.match_thresholds[cat] = max(0.0, min(1.0, float(value)))
        self.detector.set_thresholds(self.match_thresholds)
        self._save_config()
        return dict(self.detector.thresholds)

    def set_test_mode(self, value):
        self.detector.debug_image = SHOT_PATH if value else None
        self._save_config()
        return bool(self.detector.debug_image)

    def _save_config(self):
        snap = self.state.snapshot()
        data = {
            "sensitivity": self.sensitivity,
            "require_ads": snap["require_ads"],
            "hipfire_mult": snap["hipfire_mult"],
            "vk_slot1": snap["vk_slot1"],
            "vk_slot2": snap["vk_slot2"],
            "vk_toggle": snap["vk_toggle"],
            "vk_overlay": snap["vk_overlay"],
            "vk_boxes": snap["vk_boxes"],
            "ccw_enabled": snap["ccw_enabled"],
            "ccw_cooldown": snap["ccw_cooldown"],
            "auto_detect": snap["auto_detect"],
            "auto_draft_icons": self.detector.auto_draft,
            "test_mode": bool(self.detector.debug_image),
            "slot_config": self.slot_config,
            "weapon_overrides": self.weapon_overrides,
            "attachment_overrides": self.attachment_overrides,
            "match_thresholds": self.match_thresholds,
            "regions": self.detector.regions,
            "attach_slots": {str(k): v for k, v in self.detector.attach_slots.items()},
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _migrate_attachments(self):
        legacy_base = {"compensator": "comp", "flash": "flash", "suppressor": "supp", "duckbill": None}
        type_suffix = {"AR": "ar", "DMR": "sr", "SMG": "smg", "LMG": "ar", "PISTOL": "smg"}
        for cfg in self.slot_config:
            atts = cfg.get("attachments") or {}
            for cat in weapons.ATTACH_CATEGORIES:
                atts.setdefault(cat, "none")
            mz = atts.get("muzzle")
            if mz in legacy_base:
                w = self._weapon_by_id.get(cfg.get("weapon_id"))
                base = legacy_base[mz]
                new_id = "none"
                if base and w:
                    cand = f"{base}_{type_suffix.get(w['type'], 'ar')}"
                    allowed = {a["id"] for a in weapons.allowed_attachments(w, "muzzle", self._attachments)}
                    new_id = cand if cand in allowed else "none"
                atts["muzzle"] = new_id
            cfg["attachments"] = atts

    def _load_config(self):
        if not os.path.exists(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.sensitivity = float(data.get("sensitivity", 1.0))
            self.slot_config = data.get("slot_config", self.slot_config)
            self.weapon_overrides = data.get("weapon_overrides", {})
            weapons.apply_weapon_slots(data.get("weapon_slots", {}))
            self.attachment_overrides = data.get("attachment_overrides", {})
            self.match_thresholds = data.get("match_thresholds", {}) or {}
            self.detector.set_thresholds(self.match_thresholds)
            self.detector.auto_draft = bool(data.get("auto_draft_icons", True))
            if isinstance(data.get("regions"), dict) and data["regions"]:
                self.detector.regions.update({k: list(v) for k, v in data["regions"].items()})
            if isinstance(data.get("attach_slots"), dict) and data["attach_slots"]:
                self.detector.set_attach_slots(data["attach_slots"])
            self._rebuild_data()
            self._migrate_attachments()
            for cfg in self.slot_config:
                cfg["attachments"] = weapons.sanitize_attachments(cfg.get("weapon_id"), cfg.get("attachments") or {})
            with self.state.lock:
                self.state.require_ads = bool(data.get("require_ads", True))
                self.state.hipfire_mult = float(data.get("hipfire_mult", 0.5))
                self.state.vk_slot1 = int(data.get("vk_slot1", 0x31))
                self.state.vk_slot2 = int(data.get("vk_slot2", 0x32))
                self.state.vk_toggle = int(data.get("vk_toggle", 0x77))
                self.state.vk_overlay = int(data.get("vk_overlay", 0x2E))
                self.state.vk_boxes = int(data.get("vk_boxes", 0x79))
                self.state.auto_detect = bool(data.get("auto_detect", False))
                self.state.ccw_enabled = bool(data.get("ccw_enabled", False))
                self.state.ccw_cooldown = float(data.get("ccw_cooldown", 2.0))
            if data.get("test_mode"):
                self.detector.debug_image = SHOT_PATH
            self._apply_slot(0)
            self._apply_slot(1)
            self._save_config()
        except Exception:
            pass


def check_license():
    """KeyAuth Lisans Doğrulama Fonksiyonu"""
    print("--- VVIP PUBG LİSANS KONTROLÜ ---")
    license_file = os.path.join(EXE_DIR, "license.txt")
    key = ""

    # Daha önce kaydedilmiş key var mı?
    if os.path.exists(license_file):
        with open(license_file, "r", encoding="utf-8") as f:
            key = f.read().strip()

    if not key:
        key = input("Lütfen lisans anahtarınızı girin: ").strip()

    # KeyAuth ile sunucuda doğrula
    keyauthapp.license(key)

    if keyauthapp.user_data.enabled:
        print(f"[+] Lisans Başarılı! Bitiş Tarihi: {keyauthapp.user_data.expiry}")
        # Key'i kaydet ki bir daha sormasın
        with open(license_file, "w", encoding="utf-8") as f:
            f.write(key)
        return True
    else:
        print(f"[-] Hata: {keyauthapp.user_data.message}")
        input("Çıkış yapmak için Enter'a basın...")
        sys.exit(1)


def main():
    # Önce lisans kontrolü çalışır
    check_license()

    api_obj = Api()
    api_obj.engine.start()
    try:
        api_obj.overlay.start()
    except Exception:
        pass

    webview.create_window(
        "VVIP PUBG — Anti-Recoil Macro · GiYOTiN",
        os.path.join(WEB_DIR, "index.html"),
        js_api=api_obj,
        width=940,
        height=720,
        min_size=(820, 600),
        background_color="#140f22",
    )
    webview.start()
    api_obj.engine.stop()
    api_obj.controller.stop()
    try:
        api_obj.overlay.stop()
    except Exception:
        pass


if __name__ == "__main__":
    main()
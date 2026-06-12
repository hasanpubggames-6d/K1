#@j49_c by : wite wolf
import sys
import subprocess
import os

_PKG_MAP = {
    "telethon": "telethon",
    "telegram": "python-telegram-bot",
    "colorlog": "colorlog",
}

def _ensure_pkgs():
    for mod, pkg in _PKG_MAP.items():
        try:
            __import__(mod)
        except ImportError:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

_ensure_pkgs()

import json
import asyncio
import logging
from typing import Optional, Dict, Any

try:
    import colorlog
    _HAS_CLRLOG = True
except ImportError:
    _HAS_CLRLOG = False

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    Defaults,
    filters,
)
from telethon import TelegramClient, events, errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel, Chat

_TKN = "YOUR_BOT_TOKEN_HERE" #توكنك هنا

if _TKN == "YOUR_BOT_TOKEN_HERE" or ":" not in _TKN:
    print("=" * 50)
    print("خطأ: ضع التوكن الحقيقي في السطر:")
    print('BOT_TOKEN = "123456789:ABC..."')
    print("=" * 50)
    sys.exit(1)

_CFG_PATH = "config.json"
_STATE_PATH = "state.json"

if _HAS_CLRLOG:
    _hdlr = colorlog.StreamHandler()
    _hdlr.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG": "cyan", "INFO": "green", "WARNING": "yellow",
            "ERROR": "red", "CRITICAL": "bold_red",
        },
    ))
else:
    _hdlr = logging.StreamHandler()
    _hdlr.setFormatter(logging.Formatter(
        "%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    ))

_log = logging.getLogger("W0lf_Cl0n3r")
_log.addHandler(_hdlr)
_log.setLevel(logging.INFO)

def _kbd_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("تعيين المصدر", callback_data="setsource"),
         InlineKeyboardButton("تعيين الهدف", callback_data="settarget")],
        [InlineKeyboardButton("تشغيل التحويل", callback_data="start_clone"),
         InlineKeyboardButton("ايقاف التحويل", callback_data="stop_clone")],
        [InlineKeyboardButton("نسخ رسائل قديمة", callback_data="clone_old"),
         InlineKeyboardButton("الحالة", callback_data="status")],
        [InlineKeyboardButton("المساعدة", callback_data="help")]
    ])

class _CfgMgr:
    def __init__(self):
        self.aid = 0
        self.ahash = ""
        self.adm = 0
        self.src = None
        self.tgt = None
        self._pull()

    def _exists(self):
        return os.path.exists(_CFG_PATH)

    def _pull(self):
        if not self._exists():
            return
        with open(_CFG_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        self.aid = d.get("api_id", 0)
        self.ahash = d.get("api_hash", "")
        self.adm = d.get("admin_id", 0)
        self.src = d.get("source_channel")
        self.tgt = d.get("target_channel")

    def _push(self):
        with open(_CFG_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "api_id": self.aid,
                "api_hash": self.ahash,
                "admin_id": self.adm,
                "source_channel": self.src,
                "target_channel": self.tgt,
            }, f, ensure_ascii=False, indent=2)

class _StMgr:
    def __init__(self):
        self._bag = {"cloned": {}, "stats": {"total": 0, "auto": 0}}
        self._pull()

    def _pull(self):
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                self._bag = json.load(f)

    def _push(self):
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self._bag, f, ensure_ascii=False, indent=2)

    def _seen(self, mid):
        return str(mid) in self._bag["cloned"]

    def _mark(self, sid, tid):
        self._bag["cloned"][str(sid)] = tid
        self._bag["stats"]["total"] += 1
        self._push()

    def _tick_auto(self):
        self._bag["stats"]["auto"] += 1
        self._push()

    def _snap(self):
        return self._bag["stats"]

class _ClonerEngine:
    def __init__(self, cfg, st):
        self._cfg = cfg
        self._st = st
        self._tc = None
        self._se = None
        self._te = None
        self._active = False

    async def _wire(self):
        self._tc = TelegramClient(
            "wolf_session", self._cfg.aid, self._cfg.ahash,
            auto_reconnect=True, connection_retries=None, request_retries=3
        )
        await self._tc.start(bot_token=_TKN)
        me = await self._tc.get_me()
        _log.info(f"Telethon connected as {me.first_name}")
        if self._cfg.src:
            await self._set_src(self._cfg.src, True)
        if self._cfg.tgt:
            await self._set_tgt(self._cfg.tgt, True)
        self._tc.on(events.NewMessage)(self._on_new)

    async def _unwire(self):
        if self._tc:
            await self._tc.disconnect()

    async def _loop(self):
        if self._tc:
            await self._tc.run_until_disconnected()

    async def _resolve(self, url):
        try:
            return await self._tc.get_entity(url)
        except ValueError:
            if "+" in url or "joinchat" in url:
                h = url.split("+")[-1].split("/")[-1]
                try:
                    await self._tc(ImportChatInviteRequest(h))
                    return await self._tc.get_entity(url)
                except Exception as e:
                    raise ValueError(f"Join failed: {e}")
            try:
                await self._tc(JoinChannelRequest(url))
                return await self._tc.get_entity(url)
            except Exception as e:
                raise ValueError(f"Resolve failed: {e}")
        except Exception as e:
            raise ValueError(f"Resolve failed: {e}")

    async def _set_src(self, url, silent=False):
        ent = await self._resolve(url)
        if not isinstance(ent, (Channel, Chat)):
            return False, "الرابط لا يشير الى قناة."
        self._se = ent
        self._cfg.src = url
        self._cfg._push()
        if not silent:
            _log.info(f"Source: {ent.title}")
        return True, f"تم تعيين المصدر: {ent.title}"

    async def _set_tgt(self, url, silent=False):
        ent = await self._resolve(url)
        if not isinstance(ent, (Channel, Chat)):
            return False, "الرابط لا يشير الى قناة."
        self._te = ent
        self._cfg.tgt = url
        self._cfg._push()
        if not silent:
            _log.info(f"Target: {ent.title}")
        return True, f"تم تعيين الهدف: {ent.title}"

    async def _start(self):
        if not self._se or not self._te:
            return False, "لم يتم تعيين القنوات بعد."
        self._active = True
        _log.info("Auto-cloning started.")
        return True, "تم تشغيل التحويل التلقائي."

    async def _stop(self):
        self._active = False
        _log.info("Auto-cloning stopped.")
        return True, "تم ايقاف التحويل التلقائي."

    async def _clone_bulk(self, limit):
        if not self._se or not self._te:
            return False, "لم يتم تعيين القنوات."
        _log.info(f"Cloning {limit} messages...")
        msgs = []
        async for m in self._tc.iter_messages(self._se, limit=limit):
            msgs.append(m)
        msgs.reverse()
        cloned = 0
        skipped = 0
        for m in msgs:
            if self._st._seen(m.id):
                skipped += 1
                continue
            if await self._copy_one(m):
                cloned += 1
                await asyncio.sleep(0.8)
        return True, f"نسخ {cloned} رسالة. تخطي {skipped} مكررة."

    async def _copy_one(self, msg):
        try:
            copied = await msg.copy(self._te)
            self._st._mark(msg.id, copied.id)
            return True
        except errors.FloodWaitError as e:
            _log.warning(f"FloodWait {e.seconds}s")
            await asyncio.sleep(e.seconds + 1)
            return await self._copy_one(msg)
        except Exception as e:
            _log.error(f"Copy failed {msg.id}: {e}")
            return False

    async def _on_new(self, event):
        if not self._active:
            return
        if not self._se or not self._te:
            return
        if event.chat_id != self._se.id:
            return
        msg = event.message
        if self._st._seen(msg.id):
            return
        if await self._copy_one(msg):
            self._st._tick_auto()
            _log.info(f"Auto-cloned {msg.id}")

_cfg = _CfgMgr()
_st = _StMgr()
_engine = _ClonerEngine(_cfg, _st)

async def _cmd_start(update, context):
    uid = update.effective_user.id
    if not _cfg._exists() or _cfg.aid == 0:
        await update.message.reply_html("مرحباً. ارسل API_ID:")
        context.user_data["_step"] = "api_id"
        return
    if uid != _cfg.adm:
        await update.message.reply_html("غير مصرح.")
        return
    ok, msg = await _engine._start()
    await update.message.reply_html(
        "الذئب الأبيض @j49_c\n\n" + msg,
        reply_markup=_kbd_main()
    )

async def _on_msg(update, context):
    uid = update.effective_user.id
    txt = update.message.text.strip()
    step = context.user_data.get("_step")

    if step == "api_id":
        try:
            _cfg.aid = int(txt)
        except ValueError:
            await update.message.reply_html("API_ID يجب ان يكون رقماً. ارسله مرة اخرى:")
            return
        context.user_data["_step"] = "api_hash"
        await update.message.reply_html("جيد. الان ارسل API_HASH:")
        return

    if step == "api_hash":
        _cfg.ahash = txt
        context.user_data["_step"] = "admin_id"
        await update.message.reply_html("الان ارسل USER_ID الخاص بك:")
        return

    if step == "admin_id":
        try:
            _cfg.adm = int(txt)
        except ValueError:
            await update.message.reply_html("USER_ID يجب ان يكون رقماً. ارسله مرة اخرى:")
            return
        _cfg._push()
        context.user_data.pop("_step", None)
        await update.message.reply_html(
            "تم حفظ الاعدادات. جاري تشغيل النظام...",
            reply_markup=_kbd_main()
        )
        try:
            await _engine._wire()
            asyncio.create_task(_engine._loop())
            _log.info("Telethon started after setup.")
        except Exception as e:
            _log.error(f"Telethon connection failed: {e}")
            await update.message.reply_html(f"فشل الاتصال: {e}")
        return

    if uid != _cfg.adm:
        return

    if step == "source":
        ok, msg = await _engine._set_src(txt)
        context.user_data.pop("_step", None)
        await update.message.reply_html(msg, reply_markup=_kbd_main())
        return

    if step == "target":
        ok, msg = await _engine._set_tgt(txt)
        if ok and _engine._se:
            await _engine._start()
            msg += "\nتم تشغيل التحويل التلقائي."
        context.user_data.pop("_step", None)
        await update.message.reply_html(msg, reply_markup=_kbd_main())
        return

    if step == "clone":
        context.user_data.pop("_step", None)
        try:
            limit = int(txt)
            if not 1 <= limit <= 1000:
                raise ValueError
        except ValueError:
            await update.message.reply_html("العدد يجب ان يكون بين 1 و 1000.", reply_markup=_kbd_main())
            return
        sts = await update.message.reply_html("جاري النسخ...")
        ok, msg = await _engine._clone_bulk(limit)
        await sts.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=_kbd_main())
        return

async def _on_clbk(update, context):
    q = update.callback_query
    uid = update.effective_user.id
    await q.answer()

    if _cfg.adm != 0 and uid != _cfg.adm:
        await q.edit_message_text("غير مصرح.", parse_mode=ParseMode.HTML)
        return

    d = q.data

    if d == "setsource":
        context.user_data["_step"] = "source"
        await q.edit_message_text(
            "ارسل رابط القناة المصدر:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("رجوع", callback_data="back")]])
        )
        return

    if d == "settarget":
        context.user_data["_step"] = "target"
        await q.edit_message_text(
            "ارسل رابط القناة الهدف:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("رجوع", callback_data="back")]])
        )
        return

    if d == "start_clone":
        ok, msg = await _engine._start()
        await q.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=_kbd_main())
        return

    if d == "stop_clone":
        ok, msg = await _engine._stop()
        await q.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=_kbd_main())
        return

    if d == "clone_old":
        context.user_data["_step"] = "clone"
        await q.edit_message_text(
            "كم رسالة تريد نسخها؟ (1-1000):",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("رجوع", callback_data="back")]])
        )
        return

    if d == "status":
        src = _engine._se.title if _engine._se else "غير محدد"
        tgt = _engine._te.title if _engine._te else "غير محدد"
        sts = "يعمل" if _engine._active else "متوقف"
        stats = _st._snap()
        await q.edit_message_text(
            f"الحالة\n\nالمصدر: {src}\nالهدف: {tgt}\nالحالة: {sts}\n"
            f"اجمالي منسوخ: {stats['total']}\nتلقائي: {stats['auto']}",
            parse_mode=ParseMode.HTML,
            reply_markup=_kbd_main()
        )
        return

    if d == "help":
        await q.edit_message_text(
            "دليل الاستخدام — الذئب الأبيض @j49_c\n\n"
            "تعيين المصدر: ارسل رابط القناة المصدر\n"
            "تعيين الهدف: ارسل رابط القناة الهدف\n"
            "التحويل يبدأ تلقائياً بعد تعيين الهدف\n\n"
            "ملاحظات:\n"
            "• يجب أن يكون البوت عضواً في القناتين (لا يشترط أن يكون مشرفاً)\n"
            "• يدعم الروابط العامة والخاصة\n"
            "• يعيد رفع الوسائط بدون Forwarded\n"
            "• يتعامل مع FloodWait واعادة الاتصال",
            parse_mode=ParseMode.HTML,
            reply_markup=_kbd_main()
        )
        return

    if d == "back":
        await q.edit_message_text(
            "الذئب الأبيض @j49_c\nالقائمة الرئيسية:",
            parse_mode=ParseMode.HTML,
            reply_markup=_kbd_main()
        )
        return

async def _main():
    app = (
        Application.builder()
        .token(_TKN)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .build()
    )

    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_msg))
    app.add_handler(CallbackQueryHandler(_on_clbk))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    if _cfg._exists() and _cfg.aid != 0:
        try:
            await _engine._wire()
            asyncio.create_task(_engine._loop())
            _log.info("Telethon connected and running.")
        except Exception as e:
            _log.error(f"Telethon connect error: {e}")
    else:
        _log.info("Waiting for setup via bot...")

    _log.info("Bot is running. Send /start to configure.")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await _engine._unwire()
        _log.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        _log.info("Interrupted by user.")
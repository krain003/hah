"""
NEXUS WALLET - Wallet Handler
Full wallet management: view balances, manage networks, create/import wallets
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from decimal import Decimal
from datetime import datetime
import asyncio
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.repositories.wallet_repository import WalletRepository
from blockchain.wallet_manager import wallet_manager, NETWORKS
from security.encryption_manager import encryption_manager
from locales.messages import get_text

logger = structlog.get_logger(__name__)
router = Router(name="wallet")


class WalletStates(StatesGroup):
    choosing_network = State()
    confirming_creation = State()
    entering_pin = State()
    importing_key = State()
    importing_mnemonic = State()


# ==================== KEYBOARDS ====================

def get_wallet_main_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Main wallet menu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 " + get_text("wallet_balances", lang), callback_data="wallet:balances"), 
        ],
        [
            InlineKeyboardButton(text="➕ " + get_text("wallet_create", lang), callback_data="wallet:create"),      
            InlineKeyboardButton(text="📥 " + get_text("wallet_import", lang), callback_data="wallet:import"),
        ],
        [
            InlineKeyboardButton(text="🔐 " + get_text("wallet_backup", lang), callback_data="wallet:backup"),     
            InlineKeyboardButton(text="📋 " + get_text("wallet_addresses", lang), callback_data="wallet:addresses"),
        ],
        [
            InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")
        ]
    ])


def get_networks_keyboard(lang: str = "en", action: str = "create") -> InlineKeyboardMarkup:
    """Network selection keyboard"""
    buttons = []
    row = []

    for network_id, config in NETWORKS.items():
        btn_text = f"{config.icon} {config.name}"
        row.append(InlineKeyboardButton(
            text=btn_text,
            callback_data=f"wallet:{action}:{network_id}"
        ))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    if action == "create":
        buttons.append([
            InlineKeyboardButton(
                text="🌐 " + get_text("wallet_all_networks", lang),
                callback_data="wallet:create:all"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="wallet")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_import_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Import options keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔑 " + get_text("import_mnemonic", lang),
                callback_data="wallet:import:mnemonic"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔐 " + get_text("import_private_key", lang),
                callback_data="wallet:import:private_key"
            )
        ],
        [
            InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="wallet")
        ]
    ])


def get_back_keyboard(callback: str, lang: str = "en") -> InlineKeyboardMarkup:
    """Simple back button"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=callback)]
    ])


# ==================== HANDLERS ====================

@router.callback_query(F.data == "wallet")
async def show_wallet_menu(callback: CallbackQuery, state: FSMContext):
    """Show main wallet menu"""
    await state.clear()

    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)

        if not user:
            await callback.answer("Please /start first", show_alert=True)
            return

        lang = user.language_code or "en"

        wallet_repo = WalletRepository()
        wallets = await wallet_repo.get_user_wallets(session, user.id)
        wallet_count = len(wallets) if wallets else 0

        text = get_text("wallet_menu", lang, count=wallet_count)

        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_wallet_main_keyboard(lang),
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer()


@router.callback_query(F.data == "wallet:balances")
async def show_balances(callback: CallbackQuery):
    """Show all wallet balances"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"

        wallet_repo = WalletRepository()
        wallets = await wallet_repo.get_user_wallets(session, user.id)

        if not wallets:
            try:
                await callback.message.edit_text(
                    get_text("wallet_empty", lang),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="➕ " + get_text("wallet_create", lang),
                            callback_data="wallet:create"
                        )],
                        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="wallet")]
                    ]),
                    parse_mode="HTML"
                )
            except Exception:
                pass
            await callback.answer()
            return

        text = get_text("wallet_balances_title", lang) + "\n\n"

        for wallet in wallets:
            network = NETWORKS.get(wallet.network)
            if not network:
                continue

            try:
                # Use await because get_balance is async
                balance = await wallet_manager.get_balance(wallet.network, wallet.address)
            except Exception:
                balance = Decimal("0")

            short_addr = f"{wallet.address[:6]}...{wallet.address[-4:]}"

            text += f"{network.icon} <b>{network.name}</b>\n"
            text += f"   💰 {balance:.6f} {network.symbol}\n"
            text += f"   📋 <code>{short_addr}</code>\n\n"

        text += f"\n🕓 Updated: {datetime.now().strftime('%H:%M:%S')}"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 " + get_text("refresh", lang), callback_data="wallet:balances:refresh")],
            [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="wallet")]
        ])

        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass

    await callback.answer()


@router.callback_query(F.data == "wallet:balances:refresh")
async def refresh_balances(callback: CallbackQuery):
    """Refresh balances"""
    await callback.answer("🔄 Refreshing...", show_alert=False)
    await show_balances(callback)


@router.callback_query(F.data == "wallet:create")
async def start_create_wallet(callback: CallbackQuery, state: FSMContext):
    """Start wallet creation - choose network"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"

    try:
        await callback.message.edit_text(
            get_text("wallet_choose_network", lang),
            reply_markup=get_networks_keyboard(lang, "create"),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await state.set_state(WalletStates.choosing_network)
    await callback.answer()


@router.callback_query(F.data.startswith("wallet:create:"))
async def create_wallet_for_network(callback: CallbackQuery, state: FSMContext):
    """Create wallet for selected network"""
    network = callback.data.split(":")[2]

    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"

        wallet_repo = WalletRepository()

        # Update UI first
        try:
            await callback.message.edit_text(
                get_text("wallet_creating", lang),
                parse_mode="HTML"
            )
        except Exception:
            pass

        try:
            if network == "all":
                mnemonic = wallet_manager.generate_mnemonic()
                created_wallets = []

                for net_id in NETWORKS.keys():
                    try:
                        logger.info(f"Creating wallet for {net_id}...")
                        existing = await wallet_repo.get_user_wallet_by_network(session, user.id, net_id)
                        if existing:
                            continue

                        # --- AWAIT HERE ---
                        wallet_data = await wallet_manager.create_wallet(net_id, mnemonic)

                        encrypted_key = encryption_manager.encrypt_private_key(wallet_data.private_key)
                        encrypted_mnemonic = encryption_manager.encrypt_mnemonic(mnemonic, user.pin_hash[:16])       

                        wallet = await wallet_repo.create(
                            session,
                            user_id=user.id,
                            network=net_id,
                            address=wallet_data.address,
                            encrypted_private_key=encrypted_key,
                            encrypted_mnemonic=encrypted_mnemonic,
                            derivation_path=wallet_data.derivation_path
                        )
                        created_wallets.append(wallet)
                        logger.info(f"Wallet {net_id} created successfully")
                    except Exception as e:
                        logger.error(f"Failed to create {net_id} wallet", error=str(e))
                        continue

                await session.commit()

                text = get_text("wallet_created_all", lang, count=len(created_wallets))
                text += "\n\n⚠️ <b>" + get_text("backup_warning", lang) + "</b>"

            else:
                logger.info(f"Creating single wallet for {network}...")
                existing = await wallet_repo.get_user_wallet_by_network(session, user.id, network)
                if existing:
                    await callback.message.edit_text(
                        get_text("wallet_already_exists", lang),
                        reply_markup=get_back_keyboard("wallet", lang),
                        parse_mode="HTML"
                    )
                    await state.clear()
                    await callback.answer()
                    return

                config = NETWORKS[network]

                # --- AWAIT HERE ---
                logger.info("Generating keys...")
                wallet_data = await wallet_manager.create_wallet(network)
                logger.info(f"Keys generated for {wallet_data.address}")

                encrypted_key = encryption_manager.encrypt_private_key(wallet_data.private_key)
                encrypted_mnemonic = None
                
                if wallet_data.mnemonic:
                    encrypted_mnemonic = encryption_manager.encrypt_mnemonic(
                        wallet_data.mnemonic,
                        user.pin_hash[:16]
                    )

                logger.info("Saving to database...")
                wallet = await wallet_repo.create(
                    session,
                    user_id=user.id,
                    network=network,
                    address=wallet_data.address,
                    encrypted_private_key=encrypted_key,
                    encrypted_mnemonic=encrypted_mnemonic,
                    derivation_path=wallet_data.derivation_path
                )
                await session.commit()
                logger.info("Wallet saved to DB")

                short_addr = f"{wallet.address[:8]}...{wallet.address[-6:]}"
                text = get_text("wallet_created_single", lang,
                               network=config.name,
                               icon=config.icon,
                               address=short_addr)
                text += "\n\n⚠️ <b>" + get_text("backup_warning", lang) + "</b>"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔐 " + get_text("wallet_backup", lang),
                    callback_data="wallet:backup"
                )],
                [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="wallet")]
            ])

            try:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                pass

        except Exception as e:
            logger.error(f"CRITICAL ERROR creating wallet {network}", error=str(e), exc_info=True)
            try:
                await callback.message.edit_text(
                    f"❌ <b>Creation Failed</b>\n\nError: {str(e)[:100]}\n\nPlease try again later.",
                    reply_markup=get_back_keyboard("wallet", lang),
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "wallet:import")
async def show_import_options(callback: CallbackQuery):
    """Show import options"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"

    try:
        await callback.message.edit_text(
            get_text("wallet_import_choose", lang),
            reply_markup=get_import_keyboard(lang),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data == "wallet:import:mnemonic")
async def start_import_mnemonic(callback: CallbackQuery, state: FSMContext):
    """Start mnemonic import"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"

    await state.update_data(lang=lang)

    try:
        await callback.message.edit_text(
            get_text("wallet_enter_mnemonic", lang),
            reply_markup=get_back_keyboard("wallet:import", lang),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await state.set_state(WalletStates.importing_mnemonic)
    await callback.answer()


@router.message(WalletStates.importing_mnemonic)
async def process_mnemonic_import(message: Message, state: FSMContext):
    """Process mnemonic import"""
    mnemonic = message.text.strip().lower()
    data = await state.get_data()
    lang = data.get("lang", "en")

    try:
        await message.delete()
    except Exception:
        pass

    if not wallet_manager.validate_mnemonic(mnemonic):
        await message.answer(
            get_text("wallet_invalid_mnemonic", lang),
            reply_markup=get_back_keyboard("wallet:import", lang),
            parse_mode="HTML"
        )
        return

    status_msg = await message.answer(
        get_text("wallet_importing", lang),
        parse_mode="HTML"
    )

    try:
        async with db_manager.session() as session:
            user_repo = UserRepository()
            user = await user_repo.get_by_telegram_id(session, message.from_user.id)
            wallet_repo = WalletRepository()

            created_count = 0

            # Iterate over networks and create wallets
            for network in NETWORKS:
                try:
                    # --- AWAIT HERE ---
                    wallet_data = await wallet_manager.create_wallet(network, mnemonic)

                    existing = await wallet_repo.get_by_address(session, wallet_data.address)
                    if existing:
                        continue

                    encrypted_key = encryption_manager.encrypt_private_key(wallet_data.private_key)
                    encrypted_mnemonic = encryption_manager.encrypt_mnemonic(mnemonic, user.pin_hash[:16])

                    await wallet_repo.create(
                        session,
                        user_id=user.id,
                        network=network,
                        address=wallet_data.address,
                        encrypted_private_key=encrypted_key,
                        encrypted_mnemonic=encrypted_mnemonic,
                        derivation_path=wallet_data.derivation_path,
                        is_imported=True
                    )
                    created_count += 1
                except Exception as e:
                    logger.warning(f"Failed to import {network}", error=str(e))
                    continue

            await session.commit()

            text = get_text("wallet_imported", lang, count=created_count)

            await status_msg.edit_text(
                text,
                reply_markup=get_back_keyboard("wallet", lang),
                parse_mode="HTML"
            )

            logger.info("Wallets imported", user_id=user.id, count=created_count)

    except Exception as e:
        logger.error("Import failed", error=str(e))
        await status_msg.edit_text(
            get_text("error_generic", lang),
            reply_markup=get_back_keyboard("wallet", lang),
            parse_mode="HTML"
        )

    await state.clear()


@router.callback_query(F.data == "wallet:import:private_key")
async def start_import_private_key(callback: CallbackQuery, state: FSMContext):
    """Start private key import"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"

    await state.update_data(lang=lang)

    try:
        await callback.message.edit_text(
            get_text("wallet_choose_network_import", lang),
            reply_markup=get_networks_keyboard(lang, "import_pk"),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith("wallet:import_pk:"))
async def choose_network_for_pk_import(callback: CallbackQuery, state: FSMContext):
    """Choose network for private key import"""
    network = callback.data.split(":")[2]

    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"

    await state.update_data(lang=lang, import_network=network)

    config = NETWORKS[network]

    try:
        await callback.message.edit_text(
            get_text("wallet_enter_private_key", lang, network=config.name),
            reply_markup=get_back_keyboard("wallet:import", lang),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await state.set_state(WalletStates.importing_key)
    await callback.answer()


@router.message(WalletStates.importing_key)
async def process_private_key_import(message: Message, state: FSMContext):
    """Process private key import"""
    private_key = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")
    network = data.get("import_network", "ethereum")

    try:
        await message.delete()
    except Exception:
        pass

    try:
        # Import from PK is synchronous in wallet_manager
        wallet_data = wallet_manager.import_from_private_key(network, private_key)

        async with db_manager.session() as session:
            user_repo = UserRepository()
            user = await user_repo.get_by_telegram_id(session, message.from_user.id)
            wallet_repo = WalletRepository()

            existing = await wallet_repo.get_by_address(session, wallet_data.address)
            if existing:
                await message.answer(
                    get_text("wallet_already_exists", lang),
                    reply_markup=get_back_keyboard("wallet", lang),
                    parse_mode="HTML"
                )
                await state.clear()
                return

            encrypted_key = encryption_manager.encrypt_private_key(private_key)

            await wallet_repo.create(
                session,
                user_id=user.id,
                network=network,
                address=wallet_data.address,
                encrypted_private_key=encrypted_key,
                is_imported=True
            )
            await session.commit()

            config = NETWORKS[network]
            short_addr = f"{wallet_data.address[:8]}...{wallet_data.address[-6:]}"

            await message.answer(
                get_text("wallet_pk_imported", lang,
                        network=config.name,
                        icon=config.icon,
                        address=short_addr),
                reply_markup=get_back_keyboard("wallet", lang),
                parse_mode="HTML"
            )

            logger.info("Wallet imported from PK", user_id=user.id, network=network)

    except Exception as e:
        logger.error("PK import failed", error=str(e))
        await message.answer(
            get_text("wallet_invalid_key", lang),
            reply_markup=get_back_keyboard("wallet:import", lang),
            parse_mode="HTML"
        )

    await state.clear()


@router.callback_query(F.data == "wallet:addresses")
async def show_addresses(callback: CallbackQuery):
    """Show all wallet addresses"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"

        wallet_repo = WalletRepository()
        wallets = await wallet_repo.get_user_wallets(session, user.id)

        if not wallets:
            try:
                await callback.message.edit_text(
                    get_text("wallet_empty", lang),
                    reply_markup=get_back_keyboard("wallet", lang),
                    parse_mode="HTML"
                )
            except Exception:
                pass
            await callback.answer()
            return

        text = get_text("wallet_addresses_title", lang) + "\n\n"

        for wallet in wallets:
            network = NETWORKS.get(wallet.network)
            if not network:
                continue

            text += f"{network.icon} <b>{network.name}</b>\n"
            text += f"<code>{wallet.address}</code>\n\n"

        text += "💡 " + get_text("wallet_tap_to_copy", lang)

        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_back_keyboard("wallet", lang),
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer()


@router.callback_query(F.data == "wallet:backup")
async def show_backup_warning(callback: CallbackQuery, state: FSMContext):
    """Show backup warning and ask for PIN"""
    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
        lang = user.language_code or "en"

    await state.update_data(lang=lang, action="backup")

    try:
        await callback.message.edit_text(
            get_text("wallet_backup_warning", lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✅ " + get_text("understand_continue", lang),
                    callback_data="wallet:backup:confirm"
                )],
                [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="wallet")]
            ]),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data == "wallet:backup:confirm")
async def request_pin_for_backup(callback: CallbackQuery, state: FSMContext):
    """Request PIN for backup"""
    data = await state.get_data()
    lang = data.get("lang", "en")

    try:
        await callback.message.edit_text(
            get_text("enter_pin", lang),
            reply_markup=get_back_keyboard("wallet", lang),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await state.set_state(WalletStates.entering_pin)
    await callback.answer()


@router.message(WalletStates.entering_pin)
async def verify_pin_and_show_backup(message: Message, state: FSMContext):
    """Verify PIN and show mnemonic"""
    pin = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "en")

    try:
        await message.delete()
    except Exception:
        pass

    async with db_manager.session() as session:
        user_repo = UserRepository()
        user = await user_repo.get_by_telegram_id(session, message.from_user.id)

        if not encryption_manager.verify_pin(pin, user.pin_hash):
            await message.answer(
                get_text("pin_incorrect", lang),
                reply_markup=get_back_keyboard("wallet", lang),
                parse_mode="HTML"
            )
            await state.clear()
            return

        wallet_repo = WalletRepository()
        wallets = await wallet_repo.get_user_wallets(session, user.id)

        mnemonic = None
        for wallet in wallets:
            if wallet.encrypted_mnemonic:
                try:
                    mnemonic = encryption_manager.decrypt_mnemonic(
                        wallet.encrypted_mnemonic,
                        user.pin_hash[:16]
                    )
                    break
                except Exception:
                    continue

        if not mnemonic:
            await message.answer(
                get_text("wallet_no_mnemonic", lang),
                reply_markup=get_back_keyboard("wallet", lang),
                parse_mode="HTML"
            )
            await state.clear()
            return

        words = mnemonic.split()
        formatted = ""
        for i, word in enumerate(words, 1):
            formatted += f"{i:2}. <code>{word}</code>\n"

        text = get_text("wallet_backup_mnemonic", lang) + "\n\n"
        text += formatted
        text += "\n⚠️ " + get_text("wallet_backup_never_share", lang)

        backup_msg = await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🗑️ " + get_text("delete_now", lang),
                    callback_data="wallet:backup:delete"
                )]
            ]),
            parse_mode="HTML"
        )

        async def delete_later():
            await asyncio.sleep(60)
            try:
                await backup_msg.delete()
            except Exception:
                pass

        asyncio.create_task(delete_later())

        logger.info("Backup shown", user_id=user.id)

    await state.clear()


@router.callback_query(F.data == "wallet:backup:delete")
async def delete_backup_message(callback: CallbackQuery):
    """Delete backup message immediately"""
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("✅ Deleted")
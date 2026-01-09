"""
NEXUS WALLET - Localization Messages
Supports: English, Russian, Chinese, Spanish
"""

MESSAGES = {
    # ==================== WELCOME & START ====================
    "welcome": {
        "en": """
🌟 <b>Welcome to NEXUS WALLET!</b> 🌟

The most advanced Telegram crypto wallet.

<b>What you'll get:</b>
├ 🔐 Secure multi-chain wallet
├ 💱 Instant swaps across 10+ networks
├ 🤝 P2P trading marketplace
└ 📊 Real-time portfolio tracking

<b>Supported Networks:</b>
Bitcoin • Ethereum • BSC • Polygon • Solana
Arbitrum • Avalanche • TON • TRON

🌐 <b>Choose your language:</b>
""",
        "ru": """
🌟 <b>Добро пожаловать в NEXUS WALLET!</b> 🌟

Самый продвинутый крипто-кошелёк в Telegram.

<b>Что вы получите:</b>
├ 🔐 Безопасный мультисетевой кошелёк
├ 💱 Мгновенные обмены в 10+ сетях
├ 🤝 P2P торговая площадка
└ 📊 Отслеживание портфеля в реальном времени

<b>Поддерживаемые сети:</b>
Bitcoin • Ethereum • BSC • Polygon • Solana
Arbitrum • Avalanche • TON • TRON

🌐 <b>Выберите язык:</b>
""",
        "zh": """
🌟 <b>欢迎使用 NEXUS WALLET！</b> 🌟

最先进的 Telegram 加密钱包。

<b>功能特点：</b>
├ 🔐 安全的多链钱包
├ 💱 10+ 网络即时兑换
├ 🤝 P2P 交易市场
└ 📊 实时投资组合跟踪

<b>支持的网络：</b>
Bitcoin • Ethereum • BSC • Polygon • Solana
Arbitrum • Avalanche • TON • TRON

🌐 <b>选择语言：</b>
""",
        "es": """
🌟 <b>¡Bienvenido a NEXUS WALLET!</b> 🌟

La billetera crypto más avanzada de Telegram.

<b>Lo que obtendrás:</b>
├ 🔐 Billetera multi-cadena segura
├ 💱 Intercambios instantáneos en 10+ redes
├ 🤝 Mercado de trading P2P
└ 📊 Seguimiento de portafolio en tiempo real

<b>Redes soportadas:</b>
Bitcoin • Ethereum • BSC • Polygon • Solana
Arbitrum • Avalanche • TON • TRON

🌐 <b>Elige tu idioma:</b>
"""
    },

    # ==================== PIN SETUP ====================
    "pin_setup": {
        "en": """
🔐 <b>Set Your Security PIN</b>

Your PIN will be used to:
├ 💰 Confirm transactions
├ 🔑 Access sensitive data
└ 🛡 Protect your wallet

Please enter a <b>6-digit PIN</b>:

⚠️ <i>Remember this PIN! It cannot be recovered.</i>
""",
        "ru": """
🔐 <b>Установите PIN-код</b>

Ваш PIN будет использоваться для:
├ 💰 Подтверждения транзакций
├ 🔑 Доступа к важным данным
└ 🛡 Защиты кошелька

Введите <b>6-значный PIN</b>:

⚠️ <i>Запомните этот PIN! Его нельзя восстановить.</i>
""",
        "zh": """
🔐 <b>设置安全 PIN 码</b>

您的 PIN 码将用于：
├ 💰 确认交易
├ 🔑 访问敏感数据
└ 🛡 保护您的钱包

请输入 <b>6位数字 PIN</b>：

⚠️ <i>请记住此 PIN！无法恢复。</i>
""",
        "es": """
🔐 <b>Configura tu PIN de Seguridad</b>

Tu PIN se usará para:
├ 💰 Confirmar transacciones
├ 🔑 Acceder a datos sensibles
└ 🛡 Proteger tu billetera

Ingresa un <b>PIN de 6 dígitos</b>:

⚠️ <i>¡Recuerda este PIN! No se puede recuperar.</i>
"""
    },

    "pin_confirm": {
        "en": "🔄 <b>Confirm Your PIN</b>\n\nPlease enter your PIN again:",
        "ru": "🔄 <b>Подтвердите PIN</b>\n\nВведите PIN ещё раз:",
        "zh": "🔄 <b>确认您的 PIN</b>\n\n请再次输入 PIN：",
        "es": "🔄 <b>Confirma tu PIN</b>\n\nIngresa tu PIN nuevamente:"
    },

    "pin_invalid": {
        "en": "❌ PIN must be exactly 6 digits. Please try again:",
        "ru": "❌ PIN должен содержать ровно 6 цифр. Попробуйте снова:",
        "zh": "❌ PIN 必须正好是 6 位数字。请重试：",
        "es": "❌ El PIN debe tener exactamente 6 dígitos. Intenta de nuevo:"
    },

    "pin_mismatch": {
        "en": "❌ PINs don't match. Let's start over.\n\nPlease enter a 6-digit PIN:",
        "ru": "❌ PIN-коды не совпадают. Начнём сначала.\n\nВведите 6-значный PIN:",
        "zh": "❌ PIN 不匹配。让我们重新开始。\n\n请输入 6 位数字 PIN：",
        "es": "❌ Los PINs no coinciden. Empecemos de nuevo.\n\nIngresa un PIN de 6 dígitos:"
    },

    # ==================== WALLET CREATION ====================
    "creating_wallet": {
        "en": "⏳ <b>Creating your wallet...</b>\n\n🔐 Generating secure keys...",
        "ru": "⏳ <b>Создаём кошелёк...</b>\n\n🔐 Генерируем ключи...",
        "zh": "⏳ <b>正在创建钱包...</b>\n\n🔐 生成安全密钥...",
        "es": "⏳ <b>Creando tu billetera...</b>\n\n🔐 Generando claves seguras..."
    },

    "wallet_created": {
        "en": """
🎉 <b>Welcome to NEXUS WALLET!</b>

Your wallet is ready!

🔐 <b>Your Referral Code:</b>
<code>{referral_code}</code>

<b>⚠️ Important:</b>
• Never share your PIN
• Backup your wallet in Settings

Tap the button below to start! 👇
""",
        "ru": """
🎉 <b>Добро пожаловать в NEXUS WALLET!</b>

Ваш кошелёк готов!

🔐 <b>Ваш реферальный код:</b>
<code>{referral_code}</code>

<b>⚠️ Важно:</b>
• Никогда не делитесь PIN-кодом
• Сделайте бэкап в Настройках

Нажмите кнопку ниже, чтобы начать! 👇
""",
        "zh": """
🎉 <b>欢迎使用 NEXUS WALLET！</b>

您的钱包已准备就绪！

🔐 <b>您的推荐码：</b>
<code>{referral_code}</code>

<b>⚠️ 重要：</b>
• 切勿分享您的 PIN
• 在设置中备份您的钱包

点击下方按钮开始！👇
""",
        "es": """
🎉 <b>¡Bienvenido a NEXUS WALLET!</b>

¡Tu billetera está lista!

🔐 <b>Tu Código de Referido:</b>
<code>{referral_code}</code>

<b>⚠️ Importante:</b>
• Nunca compartas tu PIN
• Haz backup en Configuración

¡Toca el botón de abajo para empezar! 👇
"""
    },

    # ==================== MAIN MENU ====================
    "main_menu": {
        "en": "👋 Welcome back, <b>{name}</b>!\n\n💼 <b>NEXUS WALLET</b>\n\nSelect an option below:",
        "ru": "👋 С возвращением, <b>{name}</b>!\n\n💼 <b>NEXUS WALLET</b>\n\nВыберите опцию:",
        "zh": "👋 欢迎回来，<b>{name}</b>！\n\n💼 <b>NEXUS WALLET</b>\n\n请选择：",
        "es": "👋 ¡Bienvenido de nuevo, <b>{name}</b>!\n\n💼 <b>NEXUS WALLET</b>\n\nSelecciona una opción:"
    },

    # ==================== BUTTONS ====================
    "btn_wallet": {
        "en": "💼 Wallet",
        "ru": "💼 Кошелёк",
        "zh": "💼 钱包",
        "es": "💼 Billetera"
    },
    "btn_send": {
        "en": "📤 Send",
        "ru": "📤 Отправить",
        "zh": "📤 发送",
        "es": "📤 Enviar"
    },
    "btn_receive": {
        "en": "📥 Receive",
        "ru": "📥 Получить",
        "zh": "📥 接收",
        "es": "📥 Recibir"
    },
    "btn_swap": {
        "en": "💱 Swap",
        "ru": "💱 Обмен",
        "zh": "💱 兑换",
        "es": "💱 Intercambiar"
    },
    "btn_p2p": {
        "en": "🤝 P2P Trade",
        "ru": "🤝 P2P Торговля",
        "zh": "🤝 P2P 交易",
        "es": "🤝 Trading P2P"
    },
    "btn_history": {
        "en": "📊 History",
        "ru": "📊 История",
        "zh": "📊 历史",
        "es": "📊 Historial"
    },
    "btn_settings": {
        "en": "⚙️ Settings",
        "ru": "⚙️ Настройки",
        "zh": "⚙️ 设置",
        "es": "⚙️ Configuración"
    },
    "btn_help": {
        "en": "❓ Help",
        "ru": "❓ Помощь",
        "zh": "❓ 帮助",
        "es": "❓ Ayuda"
    },
    "btn_back": {
        "en": "🔙 Back",
        "ru": "🔙 Назад",
        "zh": "🔙 返回",
        "es": "🔙 Volver"
    },
    "btn_cancel": {
        "en": "❌ Cancel",
        "ru": "❌ Отмена",
        "zh": "❌ 取消",
        "es": "❌ Cancelar"
    },
    "btn_open_wallet": {
        "en": "🚀 Open Wallet",
        "ru": "🚀 Открыть кошелёк",
        "zh": "🚀 打开钱包",
        "es": "🚀 Abrir Billetera"
    },
    "btn_tutorial": {
        "en": "📚 How It Works",
        "ru": "📚 Как это работает",
        "zh": "📚 使用教程",
        "es": "📚 Cómo Funciona"
    },

    # ==================== HELP ====================
    "help": {
        "en": """
📚 <b>NEXUS WALLET Help</b>

<b>Features:</b>
├ 💼 Multi-chain wallet
├ 📤 Send & Receive crypto
├ 💱 Instant token swaps
├ 🤝 P2P trading
└ 📊 Portfolio tracking

<b>Commands:</b>
/start - Restart bot
/menu - Main menu
/help - This help

<b>Support:</b> @Nexus_Support_wallet_bot
""",
        "ru": """
📚 <b>Помощь NEXUS WALLET</b>

<b>Возможности:</b>
├ 💼 Мультисетевой кошелёк
├ 📤 Отправка и получение крипты
├ 💱 Мгновенные обмены
├ 🤝 P2P торговля
└ 📊 Отслеживание портфеля

<b>Команды:</b>
/start - Перезапуск
/menu - Главное меню
/help - Эта справка

<b>Поддержка:</b> @Nexus_Support_wallet_bot
""",
        "zh": """
📚 <b>NEXUS WALLET 帮助</b>

<b>功能：</b>
├ 💼 多链钱包
├ 📤 发送和接收加密货币
├ 💱 即时代币兑换
├ 🤝 P2P 交易
└ 📊 投资组合跟踪

<b>命令：</b>
/start - 重启机器人
/menu - 主菜单
/help - 帮助

<b>支持：</b> @Nexus_Support_wallet_bot
""",
        "es": """
📚 <b>Ayuda de NEXUS WALLET</b>

<b>Características:</b>
├ 💼 Billetera multi-cadena
├ 📤 Enviar y recibir crypto
├ 💱 Intercambios instantáneos
├ 🤝 Trading P2P
└ 📊 Seguimiento de portafolio

<b>Comandos:</b>
/start - Reiniciar bot
/menu - Menú principal
/help - Esta ayuda

<b>Soporte:</b> @Nexus_Support_wallet_bot
"""
    },

    # ==================== ERRORS ====================
    "error_generic": {
        "en": "❌ <b>Something went wrong</b>\n\nPlease try again with /start",
        "ru": "❌ <b>Что-то пошло не так</b>\n\nПопробуйте снова с /start",
        "zh": "❌ <b>出错了</b>\n\n请使用 /start 重试",
        "es": "❌ <b>Algo salió mal</b>\n\nIntenta de nuevo con /start"
    },

    "not_registered": {
        "en": "Please use /start to register first.",
        "ru": "Сначала зарегистрируйтесь с помощью /start",
        "zh": "请先使用 /start 注册。",
        "es": "Por favor usa /start para registrarte primero."
    },

    # ==================== WALLET ====================
    "wallet_menu": {
        "en": "💼 <b>Wallet Manager</b>\n\n📊 You have <b>{count}</b> wallet(s)\n\nChoose an action:",
        "ru": "💼 <b>Менеджер кошельков</b>\n\n📊 У вас <b>{count}</b> кошелёк(ов)\n\nВыберите действие:",
        "zh": "💼 <b>钱包管理器</b>\n\n📊 您有 <b>{count}</b> 个钱包\n\n选择操作：",
        "es": "💼 <b>Gestor de Billeteras</b>\n\n📊 Tienes <b>{count}</b> billetera(s)\n\nElige una acción:"
    },
    "wallet_balances": {
        "en": "Balances",
        "ru": "Балансы",
        "zh": "余额",
        "es": "Saldos"
    },
    "wallet_create": {
        "en": "Create Wallet",
        "ru": "Создать кошелёк",
        "zh": "创建钱包",
        "es": "Crear Billetera"
    },
    "wallet_import": {
        "en": "Import Wallet",
        "ru": "Импортировать",
        "zh": "导入钱包",
        "es": "Importar"
    },
    "wallet_backup": {
        "en": "Backup",
        "ru": "Резервная копия",
        "zh": "备份",
        "es": "Respaldo"
    },
    "wallet_addresses": {
        "en": "My Addresses",
        "ru": "Мои адреса",
        "zh": "我的地址",
        "es": "Mis Direcciones"
    },
    "wallet_all_networks": {
        "en": "All Networks (Recommended)",
        "ru": "Все сети (Рекомендуется)",
        "zh": "所有网络（推荐）",
        "es": "Todas las Redes (Recomendado)"
    },
    "wallet_empty": {
        "en": "📭 <b>No wallets yet</b>\n\nCreate your first wallet to start!",
        "ru": "📭 <b>Кошельков пока нет</b>\n\nСоздайте первый кошелёк!",
        "zh": "📭 <b>暂无钱包</b>\n\n创建您的第一个钱包！",
        "es": "📭 <b>Sin billeteras aún</b>\n\n¡Crea tu primera billetera!"
    },
    "wallet_balances_title": {
        "en": "💰 <b>Your Balances</b>",
        "ru": "💰 <b>Ваши балансы</b>",
        "zh": "💰 <b>您的余额</b>",
        "es": "💰 <b>Tus Saldos</b>"
    },
    "wallet_choose_network": {
        "en": "🌐 <b>Choose Network</b>\n\nSelect blockchain network for your new wallet:",
        "ru": "🌐 <b>Выберите сеть</b>\n\nВыберите блокчейн для нового кошелька:",
        "zh": "🌐 <b>选择网络</b>\n\n为新钱包选择区块链网络：",
        "es": "🌐 <b>Elegir Red</b>\n\nSelecciona la red blockchain:"
    },
    "wallet_creating": {
        "en": "⏳ <b>Creating wallet...</b>\n\n🔐 Generating secure keys...",
        "ru": "⏳ <b>Создаём кошелёк...</b>\n\n🔐 Генерируем ключи...",
        "zh": "⏳ <b>创建钱包中...</b>\n\n🔐 生成安全密钥...",
        "es": "⏳ <b>Creando billetera...</b>\n\n🔐 Generando claves..."
    },
    "wallet_created_all": {
        "en": "✅ <b>Wallets Created!</b>\n\n🎉 Successfully created <b>{count}</b> wallets for all networks!",
        "ru": "✅ <b>Кошельки созданы!</b>\n\n🎉 Создано <b>{count}</b> кошельков для всех сетей!",
        "zh": "✅ <b>钱包已创建！</b>\n\n🎉 成功创建 <b>{count}</b> 个钱包！",
        "es": "✅ <b>¡Billeteras Creadas!</b>\n\n🎉 Se crearon <b>{count}</b> billeteras!"
    },
    "wallet_created_single": {
        "en": "✅ <b>Wallet Created!</b>\n\n{icon} <b>{network}</b>\n📋 <code>{address}</code>",
        "ru": "✅ <b>Кошелёк создан!</b>\n\n{icon} <b>{network}</b>\n📋 <code>{address}</code>",
        "zh": "✅ <b>钱包已创建！</b>\n\n{icon} <b>{network}</b>\n📋 <code>{address}</code>",
        "es": "✅ <b>¡Billetera Creada!</b>\n\n{icon} <b>{network}</b>\n📋 <code>{address}</code>"
    },
    "backup_warning": {
        "en": "Back up your wallet immediately!",
        "ru": "Сделайте резервную копию немедленно!",
        "zh": "请立即备份您的钱包！",
        "es": "¡Haz respaldo inmediatamente!"
    },
    "wallet_import_choose": {
        "en": "📥 <b>Import Wallet</b>\n\nChoose import method:",
        "ru": "📥 <b>Импорт кошелька</b>\n\nВыберите способ импорта:",
        "zh": "📥 <b>导入钱包</b>\n\n选择导入方式：",
        "es": "📥 <b>Importar Billetera</b>\n\nElige método de importación:"
    },
    "import_mnemonic": {
        "en": "Seed Phrase (12/24 words)",
        "ru": "Сид-фраза (12/24 слова)",
        "zh": "助记词（12/24词）",
        "es": "Frase Semilla (12/24 palabras)"
    },
    "import_private_key": {
        "en": "Private Key",
        "ru": "Приватный ключ",
        "zh": "私钥",
        "es": "Clave Privada"
    },
    "wallet_enter_mnemonic": {
        "en": "🔐 <b>Enter Seed Phrase</b>\n\nType your 12 or 24 word recovery phrase:\n\n⚠️ <i>Message will be deleted for security</i>",
        "ru": "🔐 <b>Введите сид-фразу</b>\n\nВведите 12 или 24 слова:\n\n⚠️ <i>Сообщение будет удалено для безопасности</i>",
        "zh": "🔐 <b>输入助记词</b>\n\n输入您的12或24个单词：\n\n⚠️ <i>消息将被删除以确保安全</i>",
        "es": "🔐 <b>Ingresa Frase Semilla</b>\n\nEscribe tus 12 o 24 palabras:\n\n⚠️ <i>El mensaje se eliminará por seguridad</i>"
    },
    "wallet_invalid_mnemonic": {
        "en": "❌ <b>Invalid seed phrase</b>\n\nPlease check and try again.",
        "ru": "❌ <b>Неверная сид-фраза</b>\n\nПроверьте и попробуйте снова.",
        "zh": "❌ <b>助记词无效</b>\n\n请检查后重试。",
        "es": "❌ <b>Frase semilla inválida</b>\n\nVerifica e intenta de nuevo."
    },
    "wallet_importing": {
        "en": "⏳ <b>Importing wallets...</b>",
        "ru": "⏳ <b>Импортируем кошельки...</b>",
        "zh": "⏳ <b>导入钱包中...</b>",
        "es": "⏳ <b>Importando billeteras...</b>"
    },
    "wallet_imported": {
        "en": "✅ <b>Import Complete!</b>\n\n🎉 Successfully imported <b>{count}</b> wallet(s)!",
        "ru": "✅ <b>Импорт завершён!</b>\n\n🎉 Импортировано <b>{count}</b> кошелёк(ов)!",
        "zh": "✅ <b>导入完成！</b>\n\n🎉 成功导入 <b>{count}</b> 个钱包！",
        "es": "✅ <b>¡Importación Completa!</b>\n\n🎉 Se importaron <b>{count}</b> billetera(s)!"
    },
    "wallet_choose_network_import": {
        "en": "🔑 <b>Import Private Key</b>\n\nSelect network for this key:",
        "ru": "🔑 <b>Импорт приватного ключа</b>\n\nВыберите сеть:",
        "zh": "🔑 <b>导入私钥</b>\n\n选择此密钥的网络：",
        "es": "🔑 <b>Importar Clave Privada</b>\n\nSelecciona la red:"
    },
    "wallet_enter_private_key": {
        "en": "🔑 <b>Enter Private Key</b>\n\nNetwork: <b>{network}</b>\n\nPaste your private key:\n\n⚠️ <i>Message will be deleted</i>",
        "ru": "🔑 <b>Введите приватный ключ</b>\n\nСеть: <b>{network}</b>\n\nВставьте ключ:\n\n⚠️ <i>Сообщение будет удалено</i>",
        "zh": "🔑 <b>输入私钥</b>\n\n网络：<b>{network}</b>\n\n粘贴您的私钥：\n\n⚠️ <i>消息将被删除</i>",
        "es": "🔑 <b>Ingresa Clave Privada</b>\n\nRed: <b>{network}</b>\n\nPega tu clave:\n\n⚠️ <i>El mensaje se eliminará</i>"
    },
    "wallet_already_exists": {
        "en": "⚠️ <b>Wallet already exists</b>\n\nThis address is already in your wallet.",
        "ru": "⚠️ <b>Кошелёк уже существует</b>\n\nЭтот адрес уже есть в вашем кошельке.",
        "zh": "⚠️ <b>钱包已存在</b>\n\n此地址已在您的钱包中。",
        "es": "⚠️ <b>Billetera ya existe</b>\n\nEsta dirección ya está en tu billetera."
    },
    "wallet_pk_imported": {
        "en": "✅ <b>Wallet Imported!</b>\n\n{icon} <b>{network}</b>\n📋 <code>{address}</code>",
        "ru": "✅ <b>Кошелёк импортирован!</b>\n\n{icon} <b>{network}</b>\n📋 <code>{address}</code>",
        "zh": "✅ <b>钱包已导入！</b>\n\n{icon} <b>{network}</b>\n📋 <code>{address}</code>",
        "es": "✅ <b>¡Billetera Importada!</b>\n\n{icon} <b>{network}</b>\n📋 <code>{address}</code>"
    },
    "wallet_invalid_key": {
        "en": "❌ <b>Invalid private key</b>\n\nPlease check and try again.",
        "ru": "❌ <b>Неверный приватный ключ</b>\n\nПроверьте и попробуйте снова.",
        "zh": "❌ <b>私钥无效</b>\n\n请检查后重试。",
        "es": "❌ <b>Clave privada inválida</b>\n\nVerifica e intenta de nuevo."
    },
    "wallet_addresses_title": {
        "en": "📋 <b>Your Addresses</b>",
        "ru": "📋 <b>Ваши адреса</b>",
        "zh": "📋 <b>您的地址</b>",
        "es": "📋 <b>Tus Direcciones</b>"
    },
    "wallet_tap_to_copy": {
        "en": "Tap address to copy",
        "ru": "Нажмите на адрес, чтобы скопировать",
        "zh": "点击地址复制",
        "es": "Toca la dirección para copiar"
    },
    "wallet_backup_warning": {
        "en": "⚠️ <b>SECURITY WARNING</b>\n\n🔐 You are about to view your <b>SECRET RECOVERY PHRASE</b>.\n\n❌ <b>NEVER</b> share this with anyone!\n❌ <b>NEVER</b> enter it on any website!\n❌ Anyone with this phrase can <b>STEAL ALL YOUR FUNDS</b>!\n\n✅ Write it down on paper\n✅ Store it in a safe place",
        "ru": "⚠️ <b>ВНИМАНИЕ: БЕЗОПАСНОСТЬ</b>\n\n🔐 Вы собираетесь просмотреть <b>СЕКРЕТНУЮ ФРАЗУ</b>.\n\n❌ <b>НИКОГДА</b> не делитесь ей!\n❌ <b>НИКОГДА</b> не вводите на сайтах!\n❌ Любой с этой фразой может <b>УКРАСТЬ ВСЕ СРЕДСТВА</b>!\n\n✅ Запишите на бумаге\n✅ Храните в безопасном месте",
        "zh": "⚠️ <b>安全警告</b>\n\n🔐 您即将查看<b>秘密恢复短语</b>。\n\n❌ <b>绝不</b>与任何人分享！\n❌ <b>绝不</b>在任何网站输入！\n❌ 拥有此短语的人可以<b>窃取您的所有资金</b>！\n\n✅ 写在纸上\n✅ 存放在安全的地方",
        "es": "⚠️ <b>ADVERTENCIA DE SEGURIDAD</b>\n\n🔐 Estás por ver tu <b>FRASE DE RECUPERACIÓN SECRETA</b>.\n\n❌ <b>NUNCA</b> la compartas!\n❌ <b>NUNCA</b> la ingreses en sitios web!\n❌ Cualquiera con esta frase puede <b>ROBAR TODOS TUS FONDOS</b>!\n\n✅ Escríbela en papel\n✅ Guárdala en lugar seguro"
    },
    "understand_continue": {
        "en": "I Understand, Show Phrase",
        "ru": "Понимаю, показать фразу",
        "zh": "我了解，显示短语",
        "es": "Entiendo, Mostrar Frase"
    },
    "enter_pin": {
        "en": "🔐 <b>Enter your PIN</b>\n\nTo access sensitive data, enter your 6-digit PIN:",
        "ru": "🔐 <b>Введите PIN</b>\n\nДля доступа к данным введите 6-значный PIN:",
        "zh": "🔐 <b>输入您的PIN</b>\n\n要访问敏感数据，请输入6位PIN：",
        "es": "🔐 <b>Ingresa tu PIN</b>\n\nPara acceder a datos sensibles, ingresa tu PIN de 6 dígitos:"
    },
    "pin_incorrect": {
        "en": "❌ <b>Incorrect PIN</b>\n\nPlease try again.",
        "ru": "❌ <b>Неверный PIN</b>\n\nПопробуйте снова.",
        "zh": "❌ <b>PIN错误</b>\n\n请重试。",
        "es": "❌ <b>PIN incorrecto</b>\n\nIntenta de nuevo."
    },
    "wallet_no_mnemonic": {
        "en": "⚠️ <b>No recovery phrase found</b>\n\nYour wallets were imported with private keys only.",
        "ru": "⚠️ <b>Фраза восстановления не найдена</b>\n\nКошельки импортированы только с приватными ключами.",
        "zh": "⚠️ <b>未找到恢复短语</b>\n\n您的钱包仅使用私钥导入。",
        "es": "⚠️ <b>No se encontró frase de recuperación</b>\n\nTus billeteras fueron importadas solo con claves privadas."
    },
    "wallet_backup_mnemonic": {
        "en": "🔐 <b>Your Secret Recovery Phrase</b>\n\n⚠️ Write these words down in order:",
        "ru": "🔐 <b>Ваша секретная фраза</b>\n\n⚠️ Запишите эти слова по порядку:",
        "zh": "🔐 <b>您的秘密恢复短语</b>\n\n⚠️ 按顺序写下这些词：",
        "es": "🔐 <b>Tu Frase de Recuperación Secreta</b>\n\n⚠️ Escribe estas palabras en orden:"
    },
    "wallet_backup_never_share": {
        "en": "NEVER share this with anyone! This message will auto-delete in 60 seconds.",
        "ru": "НИКОГДА не делитесь этим! Сообщение удалится через 60 секунд.",
        "zh": "绝不与任何人分享！此消息将在60秒后自动删除。",
        "es": "¡NUNCA compartas esto! Este mensaje se eliminará en 60 segundos."
    },
    "delete_now": {
        "en": "Delete Now",
        "ru": "Удалить сейчас",
        "zh": "立即删除",
        "es": "Eliminar Ahora"
    },
    "refresh": {
        "en": "Refresh",
        "ru": "Обновить",
        "zh": "刷新",
        "es": "Actualizar"
    },
    "refreshing": {
        "en": "Refreshing...",
        "ru": "Обновляем...",
        "zh": "刷新中...",
        "es": "Actualizando..."
    },
    "confirm": {
        "en": "Confirm",
        "ru": "Подтвердить",
        "zh": "确认",
        "es": "Confirmar"
    },
    "cancel": {
        "en": "Cancel",
        "ru": "Отмена",
        "zh": "取消",
        "es": "Cancelar"
    },

    # ==================== SEND ====================
    "send_choose_network": {
        "en": "📤 <b>Send Crypto</b>\n\nSelect network to send from:",
        "ru": "📤 <b>Отправить криптовалюту</b>\n\nВыберите сеть для отправки:",
        "zh": "📤 <b>发送加密货币</b>\n\n选择发送网络：",
        "es": "📤 <b>Enviar Crypto</b>\n\nSelecciona la red para enviar:"
    },
    "send_enter_address": {
        "en": "📤 <b>Send {symbol}</b>\n\n{icon} Network: <b>{network}</b>\n💰 Balance: <b>{balance} {symbol}</b>\n\nEnter recipient address:",
        "ru": "📤 <b>Отправить {symbol}</b>\n\n{icon} Сеть: <b>{network}</b>\n💰 Баланс: <b>{balance} {symbol}</b>\n\nВведите адрес получателя:",
        "zh": "📤 <b>发送 {symbol}</b>\n\n{icon} 网络：<b>{network}</b>\n💰 余额：<b>{balance} {symbol}</b>\n\n输入收款地址：",
        "es": "📤 <b>Enviar {symbol}</b>\n\n{icon} Red: <b>{network}</b>\n💰 Saldo: <b>{balance} {symbol}</b>\n\nIngresa la dirección del destinatario:"
    },
    "send_enter_amount": {
        "en": "📤 <b>Send {symbol}</b>\n\n📋 To: <code>{address}</code>\n💰 Available: <b>{balance} {symbol}</b>\n\nEnter amount to send:",
        "ru": "📤 <b>Отправить {symbol}</b>\n\n📋 Кому: <code>{address}</code>\n💰 Доступно: <b>{balance} {symbol}</b>\n\nВведите сумму:",
        "zh": "📤 <b>发送 {symbol}</b>\n\n📋 收款地址：<code>{address}</code>\n💰 可用：<b>{balance} {symbol}</b>\n\n输入发送金额：",
        "es": "📤 <b>Enviar {symbol}</b>\n\n📋 Para: <code>{address}</code>\n💰 Disponible: <b>{balance} {symbol}</b>\n\nIngresa la cantidad a enviar:"
    },
    "send_confirm": {
        "en": "📤 <b>Confirm Transaction</b>\n\n{icon} Network: <b>{network}</b>\n📋 To: <code>{address}</code>\n💰 Amount: <b>{amount} {symbol}</b>\n⛽ Fee: <b>~{fee} {symbol}</b>\n\n⚠️ Please verify all details!",
        "ru": "📤 <b>Подтвердите транзакцию</b>\n\n{icon} Сеть: <b>{network}</b>\n📋 Кому: <code>{address}</code>\n💰 Сумма: <b>{amount} {symbol}</b>\n⛽ Комиссия: <b>~{fee} {symbol}</b>\n\n⚠️ Проверьте все данные!",
        "zh": "📤 <b>确认交易</b>\n\n{icon} 网络：<b>{network}</b>\n📋 收款地址：<code>{address}</code>\n💰 金额：<b>{amount} {symbol}</b>\n⛽ 手续费：<b>~{fee} {symbol}</b>\n\n⚠️ 请核实所有详情！",
        "es": "📤 <b>Confirmar Transacción</b>\n\n{icon} Red: <b>{network}</b>\n📋 Para: <code>{address}</code>\n💰 Cantidad: <b>{amount} {symbol}</b>\n⛽ Comisión: <b>~{fee} {symbol}</b>\n\n⚠️ ¡Verifica todos los detalles!"
    },
    "send_processing": {
        "en": "⏳ <b>Processing transaction...</b>\n\nPlease wait...",
        "ru": "⏳ <b>Обработка транзакции...</b>\n\nПожалуйста, подождите...",
        "zh": "⏳ <b>处理交易中...</b>\n\n请稍候...",
        "es": "⏳ <b>Procesando transacción...</b>\n\nPor favor espera..."
    },
    "send_success": {
        "en": "✅ <b>Transaction Sent!</b>\n\n💰 Amount: <b>{amount} {symbol}</b>\n📋 To: <code>{address}</code>\n\n🔗 <a href=\"{explorer}\">View on Explorer</a>\n\nTx: <code>{tx_hash}</code>",
        "ru": "✅ <b>Транзакция отправлена!</b>\n\n💰 Сумма: <b>{amount} {symbol}</b>\n📋 Кому: <code>{address}</code>\n\n🔗 <a href=\"{explorer}\">Смотреть в Explorer</a>\n\nTx: <code>{tx_hash}</code>",
        "zh": "✅ <b>交易已发送！</b>\n\n💰 金额：<b>{amount} {symbol}</b>\n📋 收款地址：<code>{address}</code>\n\n🔗 <a href=\"{explorer}\">在浏览器中查看</a>\n\nTx: <code>{tx_hash}</code>",
        "es": "✅ <b>¡Transacción Enviada!</b>\n\n💰 Cantidad: <b>{amount} {symbol}</b>\n📋 Para: <code>{address}</code>\n\n🔗 <a href=\"{explorer}\">Ver en Explorer</a>\n\nTx: <code>{tx_hash}</code>"
    },
    "send_failed": {
        "en": "❌ <b>Transaction Failed</b>\n\nError: {error}\n\nPlease try again.",
        "ru": "❌ <b>Ошибка транзакции</b>\n\nОшибка: {error}\n\nПопробуйте снова.",
        "zh": "❌ <b>交易失败</b>\n\n错误：{error}\n\n请重试。",
        "es": "❌ <b>Transacción Fallida</b>\n\nError: {error}\n\nIntenta de nuevo."
    },
    "send_invalid_address": {
        "en": "❌ <b>Invalid address</b>\n\nPlease enter a valid {network} address.",
        "ru": "❌ <b>Неверный адрес</b>\n\nВведите корректный адрес {network}.",
        "zh": "❌ <b>地址无效</b>\n\n请输入有效的 {network} 地址。",
        "es": "❌ <b>Dirección inválida</b>\n\nIngresa una dirección {network} válida."
    },
    "send_invalid_amount": {
        "en": "❌ <b>Invalid amount</b>\n\nPlease enter a valid number.",
        "ru": "❌ <b>Неверная сумма</b>\n\nВведите корректное число.",
        "zh": "❌ <b>金额无效</b>\n\n请输入有效的数字。",
        "es": "❌ <b>Cantidad inválida</b>\n\nIngresa un número válido."
    },
    "send_insufficient_balance": {
        "en": "❌ <b>Insufficient balance</b>\n\nYou don't have enough {symbol}.\nAvailable: {balance} {symbol}",
        "ru": "❌ <b>Недостаточно средств</b>\n\nУ вас недостаточно {symbol}.\nДоступно: {balance} {symbol}",
        "zh": "❌ <b>余额不足</b>\n\n您没有足够的 {symbol}。\n可用：{balance} {symbol}",
        "es": "❌ <b>Saldo insuficiente</b>\n\nNo tienes suficiente {symbol}.\nDisponible: {balance} {symbol}"
    },
    "send_max": {
        "en": "MAX",
        "ru": "МАКС",
        "zh": "最大",
        "es": "MÁX"
    },

    # ==================== RECEIVE ====================
    "receive_choose_network": {
        "en": "📥 <b>Receive Crypto</b>\n\nSelect network to receive on:",
        "ru": "📥 <b>Получить криптовалюту</b>\n\nВыберите сеть для получения:",
        "zh": "📥 <b>接收加密货币</b>\n\n选择接收网络：",
        "es": "📥 <b>Recibir Crypto</b>\n\nSelecciona la red para recibir:"
    },
    "receive_address": {
        "en": "📥 <b>Receive {symbol}</b>\n\n{icon} Network: <b>{network}</b>\n\n📋 Your address:\n<code>{address}</code>\n\n⚠️ Only send <b>{symbol}</b> and tokens on <b>{network}</b> network to this address!",
        "ru": "📥 <b>Получить {symbol}</b>\n\n{icon} Сеть: <b>{network}</b>\n\n📋 Ваш адрес:\n<code>{address}</code>\n\n⚠️ Отправляйте только <b>{symbol}</b> и токены сети <b>{network}</b> на этот адрес!",
        "zh": "📥 <b>接收 {symbol}</b>\n\n{icon} 网络：<b>{network}</b>\n\n📋 您的地址：\n<code>{address}</code>\n\n⚠️ 只能向此地址发送 <b>{network}</b> 网络上的 <b>{symbol}</b> 和代币！",
        "es": "📥 <b>Recibir {symbol}</b>\n\n{icon} Red: <b>{network}</b>\n\n📋 Tu dirección:\n<code>{address}</code>\n\n⚠️ ¡Solo envía <b>{symbol}</b> y tokens de la red <b>{network}</b> a esta dirección!"
    },
    "receive_show_qr": {
        "en": "📱 Show QR Code",
        "ru": "📱 Показать QR-код",
        "zh": "📱 显示二维码",
        "es": "📱 Mostrar Código QR"
    },
    "receive_copy_address": {
        "en": "📋 Copy Address",
        "ru": "📋 Копировать адрес",
        "zh": "📋 复制地址",
        "es": "📋 Copiar Dirección"
    },
    "receive_share": {
        "en": "📤 Share",
        "ru": "📤 Поделиться",
        "zh": "📤 分享",
        "es": "📤 Compartir"
    },

    # ==================== SWAP ====================
    "swap_title": {
        "en": "💱 <b>Token Swap</b>\n\nExchange tokens instantly across networks.",
        "ru": "💱 <b>Обмен токенов</b>\n\nМгновенный обмен токенов между сетями.",
        "zh": "💱 <b>代币兑换</b>\n\n跨网络即时兑换代币。",
        "es": "💱 <b>Intercambio de Tokens</b>\n\nIntercambia tokens instantáneamente entre redes."
    },
    "swap_select_from": {
        "en": "Select token to swap <b>FROM</b>:",
        "ru": "Выберите токен <b>ДЛЯ ОБМЕНА</b>:",
        "zh": "选择要兑换的代币 <b>从</b>：",
        "es": "Selecciona token para intercambiar <b>DESDE</b>:"
    },
    "swap_select_to": {
        "en": "Select token to swap <b>TO</b>:",
        "ru": "Выберите токен <b>НА КОТОРЫЙ</b> обменять:",
        "zh": "选择要兑换成的代币 <b>到</b>：",
        "es": "Selecciona token para intercambiar <b>HACIA</b>:"
    },
    "swap_enter_amount": {
        "en": "💱 <b>Swap {from_symbol} → {to_symbol}</b>\n\n💰 Available: <b>{balance} {from_symbol}</b>\n\nEnter amount to swap:",
        "ru": "💱 <b>Обмен {from_symbol} → {to_symbol}</b>\n\n💰 Доступно: <b>{balance} {from_symbol}</b>\n\nВведите сумму для обмена:",
        "zh": "💱 <b>兑换 {from_symbol} → {to_symbol}</b>\n\n💰 可用：<b>{balance} {from_symbol}</b>\n\n输入兑换金额：",
        "es": "💱 <b>Intercambiar {from_symbol} → {to_symbol}</b>\n\n💰 Disponible: <b>{balance} {from_symbol}</b>\n\nIngresa cantidad a intercambiar:"
    },
    "swap_quote": {
        "en": "💱 <b>Swap Quote</b>\n\n📤 From: <b>{from_amount} {from_symbol}</b>\n📥 To: <b>~{to_amount} {to_symbol}</b>\n\n💹 Rate: 1 {from_symbol} = {rate} {to_symbol}\n⛽ Fee: ~${fee_usd}\n📊 Slippage: {slippage}%\n\n⚠️ Price may change",
        "ru": "💱 <b>Котировка обмена</b>\n\n📤 От: <b>{from_amount} {from_symbol}</b>\n📥 К: <b>~{to_amount} {to_symbol}</b>\n\n💹 Курс: 1 {from_symbol} = {rate} {to_symbol}\n⛽ Комиссия: ~${fee_usd}\n📊 Проскальзывание: {slippage}%\n\n⚠️ Цена может измениться",
        "zh": "💱 <b>兑换报价</b>\n\n📤 从：<b>{from_amount} {from_symbol}</b>\n📥 到：<b>~{to_amount} {to_symbol}</b>\n\n💹 汇率：1 {from_symbol} = {rate} {to_symbol}\n⛽ 手续费：~${fee_usd}\n📊 滑点：{slippage}%\n\n⚠️ 价格可能变动",
        "es": "💱 <b>Cotización de Intercambio</b>\n\n📤 Desde: <b>{from_amount} {from_symbol}</b>\n📥 Hacia: <b>~{to_amount} {to_symbol}</b>\n\n💹 Tasa: 1 {from_symbol} = {rate} {to_symbol}\n⛽ Comisión: ~${fee_usd}\n📊 Deslizamiento: {slippage}%\n\n⚠️ El precio puede cambiar"
    },
    "swap_confirm": {
        "en": "✅ Confirm Swap",
        "ru": "✅ Подтвердить обмен",
        "zh": "✅ 确认兑换",
        "es": "✅ Confirmar Intercambio"
    },
    "swap_processing": {
        "en": "⏳ <b>Processing swap...</b>\n\nThis may take a moment...",
        "ru": "⏳ <b>Обработка обмена...</b>\n\nЭто может занять некоторое время...",
        "zh": "⏳ <b>处理兑换中...</b>\n\n这可能需要一些时间...",
        "es": "⏳ <b>Procesando intercambio...</b>\n\nEsto puede tomar un momento..."
    },
    "swap_success": {
        "en": "✅ <b>Swap Complete!</b>\n\n📤 Sent: <b>{from_amount} {from_symbol}</b>\n📥 Received: <b>{to_amount} {to_symbol}</b>\n\n🔗 <a href=\"{explorer}\">View on Explorer</a>",
        "ru": "✅ <b>Обмен завершён!</b>\n\n📤 Отправлено: <b>{from_amount} {from_symbol}</b>\n📥 Получено: <b>{to_amount} {to_symbol}</b>\n\n🔗 <a href=\"{explorer}\">Смотреть в Explorer</a>",
        "zh": "✅ <b>兑换完成！</b>\n\n📤 已发送：<b>{from_amount} {from_symbol}</b>\n📥 已收到：<b>{to_amount} {to_symbol}</b>\n\n🔗 <a href=\"{explorer}\">在浏览器中查看</a>",
        "es": "✅ <b>¡Intercambio Completo!</b>\n\n📤 Enviado: <b>{from_amount} {from_symbol}</b>\n📥 Recibido: <b>{to_amount} {to_symbol}</b>\n\n🔗 <a href=\"{explorer}\">Ver en Explorer</a>"
    },

    # ==================== P2P ====================
    "p2p_menu": {
        "en": "🤝 <b>P2P Trading</b>\n\nBuy and sell crypto directly with other users.\n\n💰 Escrow-protected trades\n⭐ Reputation system\n🌍 Multiple payment methods",
        "ru": "🤝 <b>P2P Торговля</b>\n\nПокупайте и продавайте крипту напрямую с другими пользователями.\n\n💰 Сделки защищены эскроу\n⭐ Система репутации\n🌍 Множество способов оплаты",
        "zh": "🤝 <b>P2P 交易</b>\n\n与其他用户直接买卖加密货币。\n\n💰 托管保护交易\n⭐ 信誉系统\n🌍 多种支付方式",
        "es": "🤝 <b>Trading P2P</b>\n\nCompra y vende crypto directamente con otros usuarios.\n\n💰 Operaciones protegidas por escrow\n⭐ Sistema de reputación\n🌍 Múltiples métodos de pago"
    },
    "p2p_buy": {
        "en": "💰 Buy Crypto",
        "ru": "💰 Купить крипто",
        "zh": "💰 购买加密货币",
        "es": "💰 Comprar Crypto"
    },
    "p2p_sell": {
        "en": "💸 Sell Crypto",
        "ru": "💸 Продать крипто",
        "zh": "💸 出售加密货币",
        "es": "💸 Vender Crypto"
    },
    "p2p_my_orders": {
        "en": "📋 My Orders",
        "ru": "📋 Мои ордера",
        "zh": "📋 我的订单",
        "es": "📋 Mis Órdenes"
    },
    "p2p_my_trades": {
        "en": "🔄 My Trades",
        "ru": "🔄 Мои сделки",
        "zh": "🔄 我的交易",
        "es": "🔄 Mis Operaciones"
    },
    "p2p_create_order": {
        "en": "➕ Create Order",
        "ru": "➕ Создать ордер",
        "zh": "➕ 创建订单",
        "es": "➕ Crear Orden"
    },

    # ==================== HISTORY ====================
    "history_title": {
        "en": "📊 <b>Transaction History</b>",
        "ru": "📊 <b>История транзакций</b>",
        "zh": "📊 <b>交易历史</b>",
        "es": "📊 <b>Historial de Transacciones</b>"
    },
    "history_empty": {
        "en": "📭 <b>No transactions yet</b>\n\nYour transaction history will appear here.",
        "ru": "📭 <b>Транзакций пока нет</b>\n\nВаша история транзакций появится здесь.",
        "zh": "📭 <b>暂无交易</b>\n\n您的交易历史将显示在这里。",
        "es": "📭 <b>Sin transacciones aún</b>\n\nTu historial de transacciones aparecerá aquí."
    },
    "history_item": {
        "en": "{icon} <b>{type}</b> | {amount} {symbol}\n   {status} | {date}",
        "ru": "{icon} <b>{type}</b> | {amount} {symbol}\n   {status} | {date}",
        "zh": "{icon} <b>{type}</b> | {amount} {symbol}\n   {status} | {date}",
        "es": "{icon} <b>{type}</b> | {amount} {symbol}\n   {status} | {date}"
    },
    "history_filter_all": {
        "en": "All",
        "ru": "Все",
        "zh": "全部",
        "es": "Todo"
    },
    "history_filter_send": {
        "en": "Sent",
        "ru": "Отправленные",
        "zh": "已发送",
        "es": "Enviados"
    },
    "history_filter_receive": {
        "en": "Received",
        "ru": "Полученные",
        "zh": "已接收",
        "es": "Recibidos"
    },
    "history_filter_swap": {
        "en": "Swaps",
        "ru": "Обмены",
        "zh": "兑换",
        "es": "Intercambios"
    },

    # ==================== SETTINGS ====================
    "settings_menu": {
        "en": "⚙️ <b>Settings</b>\n\nManage your wallet preferences:",
        "ru": "⚙️ <b>Настройки</b>\n\nУправление настройками кошелька:",
        "zh": "⚙️ <b>设置</b>\n\n管理您的钱包偏好：",
        "es": "⚙️ <b>Configuración</b>\n\nAdministra las preferencias de tu billetera:"
    },
    "settings_language": {
        "en": "🌐 Language",
        "ru": "🌐 Язык",
        "zh": "🌐 语言",
        "es": "🌐 Idioma"
    },
    "settings_currency": {
        "en": "💵 Currency",
        "ru": "💵 Валюта",
        "zh": "💵 货币",
        "es": "💵 Moneda"
    },
    "settings_security": {
        "en": "🔐 Security",
        "ru": "🔐 Безопасность",
        "zh": "🔐 安全",
        "es": "🔐 Seguridad"
    },
    "settings_notifications": {
        "en": "🔔 Notifications",
        "ru": "🔔 Уведомления",
        "zh": "🔔 通知",
        "es": "🔔 Notificaciones"
    },
    "settings_change_pin": {
        "en": "🔑 Change PIN",
        "ru": "🔑 Сменить PIN",
        "zh": "🔑 更改 PIN",
        "es": "🔑 Cambiar PIN"
    },
    "settings_2fa": {
        "en": "🛡 Two-Factor Auth",
        "ru": "🛡 Двухфакторная аутентификация",
        "zh": "🛡 双重认证",
        "es": "🛡 Autenticación de Dos Factores"
    },
    "settings_referral": {
        "en": "👥 Referral Program",
        "ru": "👥 Реферальная программа",
        "zh": "👥 推荐计划",
        "es": "👥 Programa de Referidos"
    },
    "settings_language_changed": {
        "en": "✅ Language changed to English",
        "ru": "✅ Язык изменён на Русский",
        "zh": "✅ 语言已更改为中文",
        "es": "✅ Idioma cambiado a Español"
    },
}


def get_text(key: str, lang: str = "en", **kwargs) -> str:
    """Get localized text"""
    if key not in MESSAGES:
        return f"[Missing: {key}]"

    msg = MESSAGES[key]

    if isinstance(msg, dict):
        text = msg.get(lang, msg.get("en", f"[Missing: {key}]"))
    else:
        text = msg

    # Format with kwargs
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass

    return text


def get_user_lang(user) -> str:
    """Get user's language code"""
    if hasattr(user, 'language_code') and user.language_code:
        lang = user.language_code[:2].lower()
        if lang in ['en', 'ru', 'zh', 'es']:
            return lang
    return 'en'
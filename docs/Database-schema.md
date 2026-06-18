# Схема базы данных PostgreSQL

База: `coworking_123456`, 13 таблиц. Геометрия планировки (координаты, размеры, стены) — в файле `static/layout.json`, не в PostgreSQL.

**Не входит в схему** (устаревшие БД): `doors`, `walls`, `services`, `tariffs`, `subscription_templates`.

---

## Политики удаления и обновления (логика)

| Политика | Когда используется | Зачем |
|----------|-------------------|--------|
| **ON DELETE CASCADE** | Иерархия «составляет часть»: этаж в коворкинге, зона на этаже, место в зоне, тариф в категории | При удалении родителя удаляются зависимые записи, не остаётся «осиротевших» строк |
| **ON DELETE SET NULL** | Ссылка на классификатор или необязательную связь | Родитель удалён — поле обнуляется, основная запись (бронь, место, уведомление) сохраняется |
| **ON DELETE RESTRICT** | История бронирований и оценок | На уровне БД: не удалить строку пользователя или места, если есть брони/оценки. В приложении удаление пользователей **не используется** |
| **ON UPDATE CASCADE** | `coworking_schedules.id_coworking` | При изменении PK коворкинга обновляется ссылка в расписании |

**Учётные записи в приложении:** клиентов и сотрудников **не удаляют** — только **блокируют** (`users.active = FALSE`). Вход запрещён, но брони, абонементы, оценки и уведомления **остаются в БД** для истории и отчётов. Ограничения ON DELETE в PostgreSQL — страховка на уровне БД (ручное удаление, админка pgAdmin), не штатный сценарий интерфейса.

**Важно:** удаление коворкинга или зоны с местами **не выполнится**, если на эти места есть бронирования (RESTRICT на `bookings.place_id`).

---

## Таблица 1 — сущности и атрибуты

### users (Пользователи)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_user | INTEGER | Да | Да | PK, SERIAL. Внутренний номер учётной записи |
| email | VARCHAR(120) | Да | Нет | Уникальный индекс. Почта; логин при входе «Почта». Обязателен при самостоятельной регистрации |
| username | VARCHAR(80) | Нет | Да | Отображаемое имя (ФИО) в интерфейсе и уведомлениях |
| password_hash | VARCHAR(200) | Нет | Да | Хеш пароля; проверка при входе |
| phone | VARCHAR(20) | Да | Нет | Уникальный индекс. Телефон `+7 XXX XXX XX XX`; логин «Телефон». Обязателен при быстрой регистрации |
| role | VARCHAR(20) | Нет | Да | DEFAULT `client`. `admin`, `manager`, `client` |
| visitor_kind | VARCHAR(20) | Нет | Да | DEFAULT `tariff`. Для клиентов: `tariff` или `subscription` |
| active | BOOLEAN | Нет | Да | DEFAULT TRUE. FALSE — учётная запись **заблокирована** (вход запрещён); в приложении это основной способ «отключить» клиента, без удаления из БД |
| created_at | TIMESTAMP | Нет | Нет | DEFAULT NOW(). Дата регистрации |
| last_login | TIMESTAMP | Нет | Нет | Время последнего входа |

У каждой записи — **email или phone** (или оба). **Удаление пользователей в интерфейсе не предусмотрено** — только блокировка через `active`.

---

### coworkings (Коворкинги)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_coworking | INTEGER | Да | Да | PK, SERIAL. Идентификатор площадки |
| name | VARCHAR(120) | Нет | Да | Название коворкинга |
| address | VARCHAR(255) | Нет | Да | Адрес площадки |

---

### floors (Этажи)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_floor | INTEGER | Да | Да | PK, SERIAL. Идентификатор этажа |
| coworking_id | INTEGER | Нет | Да | FK → `coworkings.id_coworking`, **ON DELETE CASCADE**. Площадка; при удалении коворкинга этажи удаляются |
| number | INTEGER | Нет | Да | Номер этажа (1, 2, 3 …) |
| name | VARCHAR(80) | Нет | Нет | Название этажа |

---

### location_zone_types (Типы зон)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_zone_type | INTEGER | Да | Да | PK, SERIAL. Идентификатор типа зоны |
| letter | VARCHAR(4) | Да | Да | Уникальная буква (A, B …) в коде места |
| name | VARCHAR(120) | Нет | Да | Название типа зоны |
| kind | VARCHAR(40) | Нет | Да | DEFAULT `desk_zone`. `desk_zone`, `room_zone`, `kitchen_zone`, `lounge_zone`, `wc_zone` |
| description | TEXT | Нет | Нет | Пояснение для админки |
| active | BOOLEAN | Нет | Да | DEFAULT TRUE. Архивные типы — FALSE |

---

### locations (Локации)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_location | INTEGER | Да | Да | PK, SERIAL. Логическая зона на этаже |
| floor_id | INTEGER | Нет | Да | FK → `floors.id_floor`, **ON DELETE CASCADE**. Этаж; при удалении этажа зоны удаляются |
| zone_type_id | INTEGER | Нет | Нет | FK → `location_zone_types.id_zone_type`, **ON DELETE SET NULL**. При удалении типа зоны ссылка обнуляется |
| code | VARCHAR(16) | Да | Да | Уникальный префикс: `1A`, `2B` |
| name | VARCHAR(120) | Нет | Да | Название зоны |
| kind | VARCHAR(40) | Нет | Да | Назначение зоны. Служебные зоны не создают записи в `places` |

---

### place_categories (Категории мест)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_category | INTEGER | Да | Да | PK, SERIAL. Шаблон места |
| name | VARCHAR(100) | Нет | Да | Название категории |
| kind | VARCHAR(20) | Нет | Да | `desk` — стол, `room` — помещение |
| capacity | INTEGER | Нет | Да | DEFAULT 1. Вместимость |
| width_m | FLOAT | Нет | Да | DEFAULT 1.0. Ширина шаблона (м) |
| height_m | FLOAT | Нет | Да | DEFAULT 0.75. Высота шаблона (м) |
| description | TEXT | Нет | Нет | Описание |
| active | BOOLEAN | Нет | Да | DEFAULT TRUE |
| created_at | TIMESTAMP | Нет | Нет | DEFAULT NOW() |

---

### category_tariffs (Тарифы)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_tariff | INTEGER | Да | Да | PK, SERIAL. Идентификатор тарифа |
| category_id | INTEGER | Нет | Да | FK → `place_categories.id_category`, **ON DELETE CASCADE**. При удалении категории тарифы удаляются |
| tariff_type | VARCHAR(20) | Нет | Да | `hourly`, `weekly`, `monthly` |
| price | FLOAT | Нет | Да | Цена за период (руб.) |
| active | BOOLEAN | Нет | Да | DEFAULT TRUE |
| created_at | TIMESTAMP | Нет | Нет | DEFAULT NOW() |
| updated_at | TIMESTAMP | Нет | Нет | Дата изменения цены |

---

### places (Места)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_place | INTEGER | Да | Да | PK, SERIAL. Объект на карте |
| location_id | INTEGER | Нет | Да | FK → `locations.id_location`, **ON DELETE CASCADE**. Зона; при удалении зоны места удаляются (если нет RESTRICT от броней) |
| floor_id | INTEGER | Нет | Нет | FK → `floors.id_floor`, **ON DELETE SET NULL**. Дублирование этажа; при удалении этажа поле обнуляется |
| category_id | INTEGER | Нет | Нет | FK → `place_categories.id_category`, **ON DELETE SET NULL**. При удалении категории место остаётся без шаблона |
| code | VARCHAR(32) | Да | Да | Уникальный код. Связь с `layout.json` |
| name | VARCHAR(100) | Нет | Да | Название на карте |
| kind | VARCHAR(20) | Нет | Да | `desk` — стол, `room` — помещение |
| container_code | VARCHAR(32) | Нет | Нет | Код помещения для стола. **Не FK** — логическая связь по коду |
| enclosed | BOOLEAN | Нет | Да | DEFAULT FALSE. Закрытое помещение со стенами |
| status | VARCHAR(20) | Нет | Да | DEFAULT `free`. `occupied`, `partial`, `maintenance` |
| rating | FLOAT | Нет | Нет | DEFAULT 0. Средняя оценка (из `ratings`) |
| rating_count | INTEGER | Нет | Нет | DEFAULT 0. Число оценок |
| maintenance | BOOLEAN | Нет | Да | DEFAULT FALSE. Техобслуживание |
| active | BOOLEAN | Нет | Да | DEFAULT TRUE |
| description | TEXT | Нет | Нет | Описание |
| created_at | TIMESTAMP | Нет | Нет | DEFAULT NOW() |

Вместимость — из `place_categories.capacity`. Геометрия — в `layout.json`. Удаление места с бронями/оценками **запрещено** (RESTRICT).

---

### bookings (Бронирования)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_booking | INTEGER | Да | Да | PK, SERIAL. Номер брони |
| user_id | INTEGER | Нет | Да | FK → `users.id_user`, **ON DELETE RESTRICT**. Клиент; на уровне БД удаление пользователя с бронями запрещено. В приложении пользователи не удаляются |
| place_id | INTEGER | Нет | Да | FK → `places.id_place`, **ON DELETE RESTRICT**. Место; удаление места с бронями запрещено |
| category_tariff_id | INTEGER | Нет | Нет | FK → `category_tariffs.id_tariff`, **ON DELETE SET NULL**. Тариф расчёта; при удалении тарифа ссылка обнуляется, сумма в брони сохранена |
| subscription_id | INTEGER | Нет | Нет | FK → `subscriptions.id_subscription`, **ON DELETE SET NULL**. Абонемент; при удалении абонемента ссылка обнуляется |
| people_count | INTEGER | Нет | Да | DEFAULT 1. Число человек |
| tariff_type | VARCHAR(20) | Нет | Да | DEFAULT `hourly` |
| booking_date | DATE | Нет | Да | Дата брони |
| start_time | TIME | Нет | Да | Время начала |
| end_time | TIME | Нет | Да | Время окончания |
| duration_hours | FLOAT | Нет | Да | Длительность (ч) |
| total_price | FLOAT | Нет | Да | Стоимость (руб.) |
| status | VARCHAR(20) | Нет | Да | DEFAULT `active`. `cancelled`, `completed` |
| user_rating | FLOAT | Нет | Нет | Оценка в записи брони |
| created_at | TIMESTAMP | Нет | Нет | DEFAULT NOW() |

---

### subscriptions (Абонементы)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_subscription | INTEGER | Да | Да | PK, SERIAL |
| user_id | INTEGER | Нет | Нет | FK → `users.id_user`, **ON DELETE CASCADE**. Владелец персонального абонемента; NULL для шаблона каталога. **В приложении** при блокировке клиента (`active = FALSE`) абонемент **не удаляется** — CASCADE срабатывает только при физическом удалении строки пользователя из БД (не штатный сценарий) |
| name | VARCHAR(120) | Нет | Да | Название абонемента |
| is_template | BOOLEAN | Нет | Да | DEFAULT FALSE. Шаблон каталога (`user_id` = NULL) |
| duration_days | INTEGER | Нет | Нет | Срок (дней) |
| place_kinds | VARCHAR(200) | Нет | Нет | JSON `["desk","room"]` |
| start_date | DATE | Нет | Да | Начало действия |
| end_date | DATE | Нет | Да | Окончание |
| hours_limit | INTEGER | Нет | Нет | Лимит часов; NULL = безлимит |
| hours_used | INTEGER | Нет | Да | DEFAULT 0 |
| price | FLOAT | Нет | Да | Стоимость (руб.) |
| active | BOOLEAN | Нет | Да | DEFAULT TRUE |
| created_at | TIMESTAMP | Нет | Нет | DEFAULT NOW() |

---

### coworking_schedules (Расписание)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_schedule | INTEGER | Да | Да | PK, SERIAL |
| id_coworking | INTEGER | Нет | Да | FK → `coworkings.id_coworking`, **ON DELETE NO ACTION**, **ON UPDATE CASCADE**. Площадка; удаление коворкинга с расписанием вручную |
| day_of_week | INTEGER | Нет | Да | 0 — Пн … 6 — Вс |
| open_time | TIME | Нет | Да | Время открытия |
| close_time | TIME | Нет | Да | Время закрытия |
| is_active | BOOLEAN | Нет | Да | DEFAULT TRUE. Рабочий день |
| is_bookable | BOOLEAN | Нет | Да | DEFAULT TRUE. Доступно для брони |
| created_at | TIMESTAMP | Нет | Нет | DEFAULT NOW() |
| updated_at | TIMESTAMP | Нет | Нет | Дата изменения |

---

### notifications (Уведомления)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_notification | INTEGER | Да | Да | PK, SERIAL |
| user_id | INTEGER | Нет | Нет | FK → `users.id_user`, **ON DELETE CASCADE**. Получатель; при удалении пользователя персональные уведомления удаляются; NULL при рассылке |
| sender_id | INTEGER | Нет | Нет | FK → `users.id_user`, **ON DELETE SET NULL**. Отправитель; при удалении пользователя поле обнуляется |
| booking_id | INTEGER | Нет | Нет | FK → `bookings.id_booking`, **ON DELETE SET NULL**. При удалении брони ссылка обнуляется, текст обращения сохраняется |
| title | VARCHAR(200) | Нет | Да | Заголовок |
| message | TEXT | Нет | Да | Текст |
| target_audience | VARCHAR(20) | Нет | Да | DEFAULT `all`. `managers`, `admins`, `clients` |
| is_read | BOOLEAN | Нет | Да | DEFAULT FALSE |
| created_at | TIMESTAMP | Нет | Нет | DEFAULT NOW() |

---

### ratings (Оценки мест)

| Свойство | Тип данных | Уникальность | Обязательно | Ограничения (смысл поля) |
|----------|------------|--------------|-------------|--------------------------|
| id_rating | INTEGER | Да | Да | PK, SERIAL |
| user_id | INTEGER | Нет | Да | FK → `users.id_user`, **ON DELETE RESTRICT**. Кто оценил; удаление пользователя с оценками запрещено |
| place_id | INTEGER | Нет | Да | FK → `places.id_place`, **ON DELETE RESTRICT**. Место; удаление места с оценками запрещено |
| booking_id | INTEGER | Нет | Нет | FK → `bookings.id_booking`, **ON DELETE CASCADE**. При удалении брони связанная оценка удаляется |
| score | INTEGER | Нет | Да | Оценка 1–5 |
| comment | TEXT | Нет | Нет | Комментарий |
| created_at | TIMESTAMP | Нет | Нет | DEFAULT NOW() |

---

## Типы связей между сущностями

**Текст для пояснительной записки:**

- coworkings и floors: один-ко-многим (1:N). Связь через внешний ключ `coworking_id` в таблице `floors` (ON DELETE CASCADE). При удалении коворкинга из БД удаляются его этажи и далее зависимые зоны и места, если на места нет бронирований (RESTRICT).
- coworkings и coworking_schedules: один-ко-многим (1:N). Связь через `id_coworking` в таблице `coworking_schedules` (ON DELETE NO ACTION, ON UPDATE CASCADE). Для каждого коворкинга хранится расписание по дням недели.
- floors и locations: один-ко-многим (1:N). Связь через `floor_id` в таблице `locations` (ON DELETE CASCADE). На каждом этаже может быть несколько логических зон с уникальным префиксом кода (1A, 2B и т.д.).
- floors и places: один-ко-многим (1:N). Связь через `floor_id` в таблице `places` (ON DELETE SET NULL). Дублирование этажа для быстрого получения всех мест этажа независимо от зоны.
- location_zone_types и locations: один-ко-многим (1:N). Связь через `zone_type_id` в таблице `locations` (ON DELETE SET NULL). Тип зоны определяет букву префикса и назначение (рабочие столы, переговорные, кухня и др.).
- locations и places: один-ко-многим (1:N). Связь через `location_id` в таблице `places` (ON DELETE CASCADE). Каждое бронируемое место привязано к логической зоне этажа. Служебные зоны (кухня, санузел, зона отдыха) хранятся только в `locations` и на карте из `layout.json`, без записей в `places`.
- place_categories и places: один-ко-многим (1:N). Связь через `category_id` в таблице `places` (ON DELETE SET NULL). Категория задаёт шаблон: тип, вместимость, размеры.
- place_categories и category_tariffs: один-ко-многим (1:N). Связь через `category_id` в таблице `category_tariffs` (ON DELETE CASCADE). Для каждой категории — тарифы: часовой, недельный, месячный.
- places и places (контейнер – стол): логическая связь один-ко-многим через `container_code`: для стола (`kind = desk`) указан код помещения (`kind = room`). Не внешний ключ — связь по строковому коду в одной таблице.
- users и bookings: один-ко-многим (1:N). Связь через `user_id` в таблице `bookings` (ON DELETE RESTRICT). Один пользователь может иметь множество бронирований. В приложении пользователей **не удаляют**, только блокируют (`active = FALSE`); история броней сохраняется.
- places и bookings: один-ко-многим (1:N). Связь через `place_id` в таблице `bookings` (ON DELETE RESTRICT). Одно место может быть забронировано многократно в разные периоды.
- category_tariffs и bookings: один-ко-многим (1:N). Связь через `category_tariff_id` в таблице `bookings` (ON DELETE SET NULL). Фиксирует тариф расчёта; сумма сохранена в `total_price`.
- subscriptions и bookings: один-ко-многим (1:N). Связь через `subscription_id` в таблице `bookings` (ON DELETE SET NULL). При удалении абонемента из БД ссылка в брони обнуляется, записи брони остаются.
- users и subscriptions: один-ко-многим (1:N). Связь через `user_id` в таблице `subscriptions` (ON DELETE CASCADE). `user_id` = NULL для шаблонов каталога (`is_template = TRUE`). В приложении при **блокировке** клиента абонементы **не удаляются**; CASCADE действует только при физическом удалении строки пользователя из БД (не штатный сценарий интерфейса).
- users и ratings: один-ко-многим (1:N). Связь через `user_id` в таблице `ratings` (ON DELETE RESTRICT). История оценок сохраняется; пользователь в интерфейсе не удаляется.
- places и ratings: один-ко-многим (1:N). Связь через `place_id` в таблице `ratings` (ON DELETE RESTRICT). Оценки агрегируются в поля `rating` и `rating_count` таблицы `places`.
- bookings и ratings: один-ко-многим (1:N). Связь через `booking_id` в таблице `ratings` (ON DELETE CASCADE, поле необязательно). Позволяет привязать оценку к конкретному визиту.
- users и notifications: один-ко-многим (1:N). Связь через `user_id` в таблице `notifications` (ON DELETE CASCADE). Персональные уведомления; при массовой рассылке `user_id` может быть NULL. При блокировке пользователя уведомления **остаются**.
- users и notifications (отправитель): один-ко-многим (1:N). Связь через `sender_id` в таблице `notifications` (ON DELETE SET NULL). Администратор или менеджер, отправивший сообщение; при удалении отправителя из БД поле обнуляется.
- bookings и notifications: один-ко-многим (1:N). Связь через `booking_id` (ON DELETE SET NULL). Обращение клиента с возможной привязкой к брони.
- layout.json и places: логическая связь один-к-одному (1:1) по полю `code`. Геометрия (координаты, размеры, стены) — в JSON; бизнес-атрибуты (статус, рейтинг, категория) — в PostgreSQL.

### Сводные таблицы связей

### Иерархия пространства

| Связь | Тип | Поле FK | ON DELETE | Пояснение |
|-------|-----|---------|-----------|-----------|
| coworkings → floors | 1:N | `floors.coworking_id` | CASCADE | Удаление коворкинга удаляет этажи (далее каскад по зонам и местам, если нет RESTRICT) |
| floors → locations | 1:N | `locations.floor_id` | CASCADE | Удаление этажа удаляет зоны |
| location_zone_types → locations | 1:N | `locations.zone_type_id` | SET NULL | Удаление типа зоны — зоны остаются, `zone_type_id` = NULL |
| locations → places | 1:N | `places.location_id` | CASCADE | Удаление зоны удаляет места (если на места нет броней) |
| floors → places | 1:N | `places.floor_id` | SET NULL | Удаление этажа — `floor_id` обнуляется, место остаётся |

### Тарифы и категории

| Связь | Тип | Поле FK | ON DELETE | Пояснение |
|-------|-----|---------|-----------|-----------|
| place_categories → places | 1:N | `places.category_id` | SET NULL | Удаление категории — места без шаблона |
| place_categories → category_tariffs | 1:N | `category_tariffs.category_id` | CASCADE | Удаление категории удаляет её тарифы |
| category_tariffs → bookings | 1:N | `bookings.category_tariff_id` | SET NULL | Удаление тарифа — в брони сохраняется `total_price` |

### Бронирования и абонементы

| Связь | Тип | Поле FK | ON DELETE | Пояснение |
|-------|-----|---------|-----------|-----------|
| users → bookings | 1:N | `bookings.user_id` | RESTRICT | Брони сохраняют ссылку на клиента; в приложении клиент **блокируется**, не удаляется |
| places → bookings | 1:N | `bookings.place_id` | RESTRICT | История броней; место с бронями не удалить |
| subscriptions → bookings | 1:N | `bookings.subscription_id` | SET NULL | При удалении абонемента из БД ссылка в брони обнуляется, бронь остаётся |
| users → subscriptions | 1:N | `subscriptions.user_id` | CASCADE | Только при удалении строки пользователя из БД; блокировка (`active = FALSE`) абонемент **не трогает** |

### Оценки и уведомления

| Связь | Тип | Поле FK | ON DELETE | Пояснение |
|-------|-----|---------|-----------|-----------|
| users → ratings | 1:N | `ratings.user_id` | RESTRICT | Оценки сохраняются; пользователь в приложении не удаляется |
| places → ratings | 1:N | `ratings.place_id` | RESTRICT | История оценок; агрегат в `places.rating` |
| bookings → ratings | 1:N | `ratings.booking_id` | CASCADE | Удаление брони из БД удаляет оценку визита |
| users → notifications (получатель) | 1:N | `notifications.user_id` | CASCADE | При удалении пользователя из БД; при блокировке уведомления **остаются** |
| users → notifications (отправитель) | 1:N | `notifications.sender_id` | SET NULL | Текст уведомления сохраняется |
| bookings → notifications | 1:N | `notifications.booking_id` | SET NULL | Обращение сохраняется без ссылки на бронь |

### Расписание и внешние данные

| Связь | Тип | Поле FK | ON DELETE / ON UPDATE | Пояснение |
|-------|-----|---------|----------------------|-----------|
| coworkings → coworking_schedules | 1:N | `coworking_schedules.id_coworking` | NO ACTION / **UPDATE CASCADE** | Расписание по дням недели |
| layout.json ↔ places | 1:1 по `code` | — | — | Геометрия в JSON; не FK |
| places ↔ places (контейнер–стол) | 1:N | `container_code` | — | Логическая связь; не FK |

### Служебные зоны

Кухня, санузел, зона отдыха (`kitchen_zone`, `wc_zone`, `lounge_zone`) — только в `locations` и `layout.json`, **без** записей в `places`.

---

## Вход в систему (users)

| Сценарий | Что заполняется | Как войти |
|----------|-----------------|-----------|
| Самостоятельная регистрация | email обязателен, телефон опционально | «Почта» + пароль |
| Быстрая регистрация (менеджер) | телефон обязателен, email опционально | «Телефон» + временный пароль |

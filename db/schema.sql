create table if not exists companies (
  id serial primary key,
  name text not null,
  legal_name text,
  dot_number text,
  mc_number text,
  contact_name text,
  contact_phone text,
  contact_email text,
  timezone text not null default 'America/Chicago',
  status text not null default 'active' check (status in ('active','suspended')),
  is_house boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists users (
  id serial primary key,
  email text not null,
  name text not null,
  password_hash text not null,
  platform_role text check (platform_role in ('owner','staff')),
  telegram_chat_id bigint,
  telegram_username text,
  status text not null default 'active' check (status in ('active','disabled')),
  failed_logins int not null default 0,
  locked_until timestamptz,
  last_login_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists users_email_key on users (lower(email));

create table if not exists memberships (
  id serial primary key,
  user_id int not null references users(id) on delete cascade,
  company_id int not null references companies(id) on delete cascade,
  role text not null default 'viewer' check (role in ('admin','viewer')),
  created_at timestamptz not null default now(),
  unique (user_id, company_id)
);

create table if not exists devices (
  id bigserial primary key,
  user_id int not null references users(id) on delete cascade,
  token_hash bytea not null unique,
  label text,
  user_agent text,
  first_ip text,
  last_ip text,
  trusted_until timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

create table if not exists sessions (
  id bigserial primary key,
  user_id int not null references users(id) on delete cascade,
  device_id bigint references devices(id) on delete set null,
  company_id int references companies(id) on delete set null,
  token_hash bytea not null unique,
  csrf_secret text not null,
  ip text,
  user_agent text,
  expires_at timestamptz not null,
  absolute_expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

create table if not exists login_challenges (
  id bigserial primary key,
  user_id int not null references users(id) on delete cascade,
  code_hash bytea not null,
  handle text not null unique,
  attempts int not null default 0,
  ip text,
  user_agent text,
  expires_at timestamptz not null,
  consumed_at timestamptz,
  denied_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists telegram_links (
  id bigserial primary key,
  user_id int not null references users(id) on delete cascade,
  code text not null unique,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists invites (
  id bigserial primary key,
  company_id int references companies(id) on delete cascade,
  email text not null,
  name text not null,
  role text not null default 'viewer',
  platform_role text,
  token_hash bytea not null unique,
  invited_by int references users(id) on delete set null,
  expires_at timestamptz not null,
  accepted_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists throttle (
  key text primary key,
  count int not null default 0,
  first_at timestamptz not null default now(),
  last_at timestamptz not null default now(),
  blocked_until timestamptz
);

create table if not exists audit_log (
  id bigserial primary key,
  company_id int references companies(id) on delete set null,
  user_id int references users(id) on delete set null,
  actor text,
  action text not null,
  entity text,
  entity_id text,
  detail jsonb,
  ip text,
  created_at timestamptz not null default now()
);
create index if not exists audit_log_created_idx on audit_log (created_at desc);
create index if not exists audit_log_company_idx on audit_log (company_id, created_at desc);

create table if not exists drivers (
  id serial primary key,
  company_id int not null references companies(id) on delete cascade,
  user_id int references users(id) on delete set null,
  name text not null,
  phone text,
  email text,
  telegram_username text,
  license_number text,
  license_state text,
  license_expires date,
  medical_expires date,
  hired_on date,
  status text not null default 'active' check (status in ('active','inactive')),
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists drivers_company_idx on drivers (company_id, status);

create table if not exists trucks (
  id serial primary key,
  company_id int not null references companies(id) on delete cascade,
  unit_number text not null,
  vin text,
  make text,
  model text,
  year int,
  plate text,
  plate_state text,
  status text not null default 'active' check (status in ('active','shop','out_of_service','sold')),
  duty_cycle text not null default 'standard' check (duty_cycle in ('standard','severe')),
  odometer int not null default 0,
  odometer_at timestamptz,
  driver_id int references drivers(id) on delete set null,
  fuel_card_last4 text,
  oil_interval_miles int not null default 25000,
  pm_a_interval_miles int not null default 15000,
  pm_b_interval_miles int not null default 45000,
  registration_expires date,
  annual_inspection_on date,
  insurance_expires date,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists trucks_unit_key on trucks (company_id, lower(unit_number));
create index if not exists trucks_company_idx on trucks (company_id, status);

create table if not exists odometer_readings (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  miles int not null,
  read_at timestamptz not null default now(),
  source text not null default 'manual' check (source in ('manual','fuel','service','telematics')),
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists odometer_truck_idx on odometer_readings (truck_id, read_at desc);

create table if not exists fuel_transactions (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  driver_id int references drivers(id) on delete set null,
  purchased_at timestamptz not null,
  gallons numeric(10,3) not null,
  price_per_gallon numeric(10,4),
  total numeric(12,2) not null,
  odometer int,
  location text,
  state text,
  fuel_type text not null default 'diesel' check (fuel_type in ('diesel','def','reefer','gas')),
  card_last4 text,
  invoice_no text,
  source text not null default 'manual' check (source in ('manual','import','api')),
  raw jsonb,
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists fuel_company_idx on fuel_transactions (company_id, purchased_at desc);
create index if not exists fuel_truck_idx on fuel_transactions (truck_id, purchased_at desc);

create table if not exists maintenance_orders (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  kind text not null default 'repair' check (kind in ('oil','pm_a','pm_b','repair','tire','annual_inspection','recall')),
  status text not null default 'scheduled' check (status in ('scheduled','in_progress','done')),
  scheduled_for date,
  performed_on date,
  odometer int,
  vendor text,
  invoice_no text,
  cost numeric(12,2),
  description text not null,
  next_due_on date,
  next_due_odometer int,
  breakdown_id bigint,
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists maint_company_idx on maintenance_orders (company_id, status, performed_on desc);
create index if not exists maint_truck_idx on maintenance_orders (truck_id, performed_on desc);

create table if not exists breakdowns (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  driver_id int references drivers(id) on delete set null,
  occurred_at timestamptz not null default now(),
  resolved_at timestamptz,
  status text not null default 'open' check (status in ('open','towing','in_shop','resolved')),
  severity text not null default 'medium' check (severity in ('low','medium','high')),
  location text,
  latitude numeric(9,6),
  longitude numeric(9,6),
  description text not null,
  cause text,
  resolution text,
  load_number text,
  towing_cost numeric(12,2),
  repair_cost numeric(12,2),
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists breakdowns_company_idx on breakdowns (company_id, status, occurred_at desc);

create table if not exists breakdown_updates (
  id bigserial primary key,
  breakdown_id bigint not null references breakdowns(id) on delete cascade,
  company_id int not null references companies(id) on delete cascade,
  note text not null,
  status text,
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists breakdown_updates_idx on breakdown_updates (breakdown_id, created_at desc);

create table if not exists integrations (
  id serial primary key,
  company_id int not null references companies(id) on delete cascade,
  provider text not null default 'samsara' check (provider in ('samsara')),
  credential bytea,
  status text not null default 'disconnected' check (status in ('disconnected','connected','error')),
  last_sync_at timestamptz,
  last_error text,
  sync_cursor text,
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (company_id, provider)
);

create table if not exists vehicle_links (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int references trucks(id) on delete cascade,
  provider text not null default 'samsara',
  external_id text not null,
  external_name text,
  external_vin text,
  last_seen_at timestamptz,
  created_at timestamptz not null default now(),
  unique (company_id, provider, external_id)
);
create index if not exists vehicle_links_truck_idx on vehicle_links (truck_id);

create table if not exists fault_events (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  source text not null default 'samsara',
  protocol text not null default 'j1939' check (protocol in ('j1939','obdii','manual')),
  code_key text not null,
  spn int,
  fmi int,
  dtc_code text,
  description text,
  lamp text,
  severity text not null default 'unknown' check (severity in ('unknown','low','medium','high')),
  occurrence_count int,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  cleared_at timestamptz,
  acknowledged_at timestamptz,
  acknowledged_by int references users(id) on delete set null,
  raw jsonb,
  created_at timestamptz not null default now(),
  unique (truck_id, code_key, first_seen_at)
);
create index if not exists fault_company_idx on fault_events (company_id, cleared_at, last_seen_at desc);
create index if not exists fault_truck_idx on fault_events (truck_id, last_seen_at desc);

create table if not exists dvir_defects (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int references trucks(id) on delete set null,
  external_id text not null,
  defect_type text,
  comment text,
  reported_by text,
  is_resolved boolean not null default false,
  reported_at timestamptz,
  resolved_at timestamptz,
  raw jsonb,
  created_at timestamptz not null default now(),
  unique (company_id, external_id)
);
create index if not exists dvir_company_idx on dvir_defects (company_id, is_resolved, reported_at desc);

create table if not exists sync_runs (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  provider text not null default 'samsara',
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running' check (status in ('running','ok','error')),
  vehicles_seen int not null default 0,
  odometer_rows int not null default 0,
  faults_opened int not null default 0,
  faults_cleared int not null default 0,
  defects_seen int not null default 0,
  error text
);
create index if not exists sync_runs_idx on sync_runs (company_id, started_at desc);

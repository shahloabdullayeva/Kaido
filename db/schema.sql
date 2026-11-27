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

create table if not exists captchas (
  handle text primary key,
  answer text not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
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
  latitude numeric(9,6),
  longitude numeric(9,6),
  location text,
  located_at timestamptz,
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
  driver_id int references drivers(id) on delete set null,
  kind text not null default 'repair',
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

alter table maintenance_orders add column if not exists driver_id int references drivers(id) on delete set null;
create index if not exists maint_driver_idx on maintenance_orders (driver_id, performed_on desc);

alter table trucks add column if not exists latitude numeric(9,6);
alter table trucks add column if not exists longitude numeric(9,6);
alter table trucks add column if not exists location text;
alter table trucks add column if not exists located_at timestamptz;

create table if not exists shop_lookups (
  id bigserial primary key,
  cell text not null,
  radius_m int not null,
  payload jsonb not null,
  fetched_at timestamptz not null default now(),
  unique (cell, radius_m)
);
create index if not exists shop_lookups_age_idx on shop_lookups (fetched_at);

create table if not exists ai_usage (
  id bigserial primary key,
  model text not null,
  input_tokens int not null default 0,
  output_tokens int not null default 0,
  cost_usd numeric(10,6) not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists ai_usage_day_idx on ai_usage (created_at desc);

create table if not exists ai_cache (
  cache_key text primary key,
  model text not null,
  payload jsonb not null,
  fetched_at timestamptz not null default now()
);
create index if not exists ai_cache_age_idx on ai_cache (fetched_at);

create table if not exists geocodes (
  query text primary key,
  lat numeric(9,6) not null,
  lon numeric(9,6) not null,
  label text,
  fetched_at timestamptz not null default now()
);

alter table trucks add column if not exists is_outside boolean not null default false;
alter table trucks add column if not exists outside_carrier text;
alter table drivers add column if not exists is_outside boolean not null default false;
alter table drivers add column if not exists outside_carrier text;

alter table companies add column if not exists followup_enabled boolean not null default true;
alter table companies add column if not exists followup_hour int not null default 7;

create table if not exists reminders (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  entity text not null check (entity in ('truck','driver','maintenance_order','breakdown','fault_event','fuel_transaction')),
  entity_id bigint not null,
  note text not null,
  remind_at timestamptz not null,
  audience text not null default 'me' check (audience in ('me','admins')),
  created_by int references users(id) on delete set null,
  sent_at timestamptz,
  done_at timestamptz,
  done_by int references users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists reminders_due_idx on reminders (remind_at) where sent_at is null and done_at is null;
create index if not exists reminders_entity_idx on reminders (company_id, entity, entity_id);

create table if not exists followups (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  local_day date not null,
  recipients int not null default 0,
  body text,
  sent_at timestamptz not null default now(),
  unique (company_id, local_day)
);

create table if not exists fault_alerts (
  fault_id bigint primary key references fault_events(id) on delete cascade,
  company_id int not null references companies(id) on delete cascade,
  sent_at timestamptz not null default now()
);

create table if not exists fault_guides (
  guide_key text primary key,
  model text not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

alter table fuel_transactions add column if not exists external_ref text;
create unique index if not exists fuel_external_key on fuel_transactions (company_id, external_ref) where external_ref is not null;

create table if not exists fuel_imports (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  filename text,
  rows_total int not null default 0,
  rows_added int not null default 0,
  rows_duplicate int not null default 0,
  rows_unmatched int not null default 0,
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now()
);

alter table trucks add column if not exists engine text;
alter table trucks add column if not exists engine_liters numeric(4,1);
alter table trucks add column if not exists engine_source text;
alter table trucks add column if not exists engine_checked_at timestamptz;

create table if not exists ai_chats (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  user_id int references users(id) on delete cascade,
  truck_id int references trucks(id) on delete cascade,
  role text not null check (role in ('user','assistant')),
  content text not null,
  created_at timestamptz not null default now()
);
create index if not exists ai_chats_thread_idx on ai_chats (company_id, user_id, truck_id, created_at);

create table if not exists service_intervals (
  company_id int not null references companies(id) on delete cascade,
  kind text not null,
  miles int,
  months int,
  updated_at timestamptz not null default now(),
  primary key (company_id, kind)
);

-- Where the shop search last looked for this work order, when it was not the Samsara position.
alter table maintenance_orders add column if not exists shop_where text;
alter table maintenance_orders add column if not exists shop_lat numeric(9,6);
alter table maintenance_orders add column if not exists shop_lon numeric(9,6);

-- Shops the company trusts, usually pasted in as Google Maps links. Listed first in every search.
create table if not exists saved_shops (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  name text not null,
  address text,
  latitude numeric(9,6) not null,
  longitude numeric(9,6) not null,
  phone text,
  website text,
  maps_url text,
  place_id text,
  source_url text,
  note text,
  added_by int references users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists saved_shops_company_idx on saved_shops (company_id);

alter table integrations drop constraint if exists integrations_provider_check;
alter table integrations add constraint integrations_provider_check check (provider in ('samsara','horizoneld'));

create table if not exists driver_links (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  driver_id int references drivers(id) on delete set null,
  provider text not null default 'horizoneld',
  external_id text not null,
  external_username text,
  last_seen_at timestamptz,
  created_at timestamptz not null default now(),
  unique (company_id, provider, external_id)
);
create index if not exists driver_links_driver_idx on driver_links (driver_id);

create table if not exists hos_status (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  driver_id int references drivers(id) on delete set null,
  provider text not null default 'horizoneld',
  external_user_id text not null,
  duty_status text,
  break_remaining numeric,
  drive_remaining numeric,
  shift_remaining numeric,
  cycle_remaining numeric,
  vehicle_external_id text,
  latitude numeric(9,6),
  longitude numeric(9,6),
  odometer int,
  located_at timestamptz,
  raw jsonb,
  updated_at timestamptz not null default now(),
  unique (company_id, provider, external_user_id)
);
create index if not exists hos_status_company_idx on hos_status (company_id, duty_status);

do $$
declare
  tenant text;
begin
  foreach tenant in array array[
    'drivers','trucks','odometer_readings','fuel_transactions','maintenance_orders','breakdowns',
    'breakdown_updates','integrations','vehicle_links','fault_events','dvir_defects','sync_runs',
    'reminders','followups','fault_alerts','fuel_imports','ai_chats','service_intervals',
    'saved_shops','driver_links','hos_status'
  ] loop
    execute format('alter table %I enable row level security', tenant);
    execute format('alter table %I force row level security', tenant);
    execute format('drop policy if exists company_lock on %I', tenant);
    execute format(
      'create policy company_lock on %I using (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int) '
      'with check (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int)', tenant);
  end loop;
end $$;

create table if not exists osm_calls (
  service text primary key,
  last_at timestamptz not null default 'epoch'
);

alter table users add column if not exists can_add_companies boolean not null default false;

alter table maintenance_orders drop constraint if exists maintenance_orders_kind_check;

-- One row per billable Google Maps Platform request, for the daily cap.
create table if not exists google_calls (
  id bigserial primary key,
  sku text not null,
  created_at timestamptz not null default now()
);
create index if not exists google_calls_day_idx on google_calls (created_at desc);

alter table trucks add column if not exists pti_token text unique;

create table if not exists inspections (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int references trucks(id) on delete set null,
  driver_id int references drivers(id) on delete set null,
  driver_name text,
  kind text not null default 'pre_trip' check (kind in ('pre_trip', 'post_trip', 'mechanic', 'unspecified')),
  source text not null default 'kaido' check (source in ('kaido', 'samsara')),
  external_id text,
  odometer int,
  results jsonb not null default '{}',
  defect_count int not null default 0,
  safe_to_drive boolean,
  notes text,
  signed_name text,
  reviewed_previous_id bigint references inspections(id) on delete set null,
  submitted_at timestamptz not null default now(),
  submitted_ip text,
  created_by int references users(id) on delete set null,
  certification text check (certification in ('repaired', 'not_needed')),
  certified_note text,
  certified_name text,
  certified_by int references users(id) on delete set null,
  certified_at timestamptz,
  maintenance_order_id bigint references maintenance_orders(id) on delete set null,
  alerted_at timestamptz,
  raw jsonb,
  created_at timestamptz not null default now(),
  unique (company_id, source, external_id)
);
create index if not exists inspections_company_idx on inspections (company_id, submitted_at desc);
create index if not exists inspections_truck_idx on inspections (truck_id, submitted_at desc);
create index if not exists inspections_open_idx on inspections (company_id) where defect_count > 0 and certified_at is null;

create table if not exists inspection_photos (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  inspection_id bigint not null references inspections(id) on delete cascade,
  item text,
  path text not null,
  content_type text not null default 'image/jpeg',
  created_at timestamptz not null default now()
);
create index if not exists inspection_photos_idx on inspection_photos (inspection_id);

do $$
declare tenant text;
begin
  foreach tenant in array array['inspections', 'inspection_photos'] loop
    execute format('alter table %I enable row level security', tenant);
    execute format('alter table %I force row level security', tenant);
    execute format('drop policy if exists company_lock on %I', tenant);
    execute format(
      'create policy company_lock on %I using (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int) '
      'with check (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int)', tenant);
  end loop;
end $$;

alter table companies add column if not exists driver_chat_id bigint;
alter table companies add column if not exists driver_chat_title text;
alter table companies add column if not exists driver_link_code text;
alter table companies add column if not exists pti_messages_enabled boolean not null default true;
alter table companies add column if not exists pti_morning_hour int not null default 6;
alter table companies add column if not exists pti_evening_hour int not null default 20;

create table if not exists pti_messages (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  local_day date not null,
  kind text not null check (kind in ('morning', 'evening', 'nudge')),
  truck_id int not null default 0,
  ok boolean not null default false,
  sent_at timestamptz not null default now(),
  unique (company_id, local_day, kind, truck_id)
);

do $$
begin
  execute 'alter table pti_messages enable row level security';
  execute 'alter table pti_messages force row level security';
  execute 'drop policy if exists company_lock on pti_messages';
  execute 'create policy company_lock on pti_messages using (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
          'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int) '
          'with check (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
          'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int)';
end $$;

alter table companies add column if not exists pti_days int[] not null default '{1,4}';

alter table drivers add column if not exists telegram_user_id bigint;

alter table trucks add column if not exists telegram_chat_id bigint;
alter table trucks add column if not exists telegram_chat_title text;
alter table trucks add column if not exists telegram_link_code text unique;
alter table pti_messages add column if not exists chat_id bigint;
alter table pti_messages add column if not exists message_ids bigint[];
update trucks t set telegram_chat_id = c.driver_chat_id, telegram_chat_title = c.driver_chat_title
  from companies c
  where c.id = t.company_id and c.driver_chat_id is not null and t.telegram_chat_id is null
    and t.id = (select d.id from trucks d join drivers r on r.id = d.driver_id
                where d.company_id = c.id and r.telegram_user_id is not null order by d.id limit 1);
update companies set driver_chat_id = null, driver_chat_title = null, driver_link_code = null
  where driver_chat_id is not null;

alter table inspection_photos add column if not exists kind text not null default 'photo';
alter table inspection_photos add column if not exists bytes bigint;

alter table inspections add column if not exists ai_status text;
alter table inspections add column if not exists ai_result jsonb;
alter table inspections add column if not exists ai_checked_at timestamptz;

alter table inspections add column if not exists review_status text check (review_status in ('approved', 'rejected'));
alter table inspections add column if not exists review_note text;
alter table inspections add column if not exists reviewed_by int references users(id) on delete set null;
alter table inspections add column if not exists reviewed_name text;
alter table inspections add column if not exists reviewed_at timestamptz;

create table if not exists summaries (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  recipients int not null default 0,
  body text,
  sent_at timestamptz not null default now()
);

alter table users add column if not exists theme text not null default 'auto';
alter table users drop constraint if exists users_theme_check;
alter table users add constraint users_theme_check check (theme in ('auto', 'light', 'dark'));
alter table users add column if not exists default_company_id int references companies(id) on delete set null;

alter table saved_shops add column if not exists saved_by_name text;
alter table saved_shops add column if not exists saved_on timestamptz;
alter table saved_shops add column if not exists details_checked_at timestamptz;
alter table saved_shops add column if not exists service text;

alter table trucks add column if not exists driver_from_name boolean not null default false;

create table if not exists inspection_reviews (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  inspection_id bigint not null references inspections(id) on delete cascade,
  decision text not null check (decision in ('approved', 'rejected')),
  note text,
  reviewed_by int references users(id) on delete set null,
  reviewed_name text,
  created_at timestamptz not null default now()
);
create index if not exists inspection_reviews_idx on inspection_reviews (inspection_id, created_at);

do $$
begin
  execute 'alter table inspection_reviews enable row level security';
  execute 'alter table inspection_reviews force row level security';
  execute 'drop policy if exists company_lock on inspection_reviews';
  execute 'create policy company_lock on inspection_reviews using (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
          'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int) '
          'with check (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
          'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int)';
end $$;

alter table users add column if not exists can_see_site boolean not null default false;

create table if not exists cat_notes (
  id bigserial primary key,
  user_id int not null references users(id) on delete cascade,
  kind text not null default 'note' check (kind in ('note', 'reminder')),
  message text not null,
  sent_by int references users(id) on delete set null,
  created_at timestamptz not null default now(),
  shown_at timestamptz,
  done_at timestamptz
);
create index if not exists cat_notes_pending_idx on cat_notes (user_id, created_at) where done_at is null;

alter table maintenance_orders add column if not exists shop_phone text;
alter table maintenance_orders add column if not exists shop_address text;
alter table maintenance_orders add column if not exists driver_contact text;
alter table maintenance_orders add column if not exists labor_cost numeric(12,2);
alter table maintenance_orders add column if not exists tax numeric(12,2);
alter table maintenance_orders add column if not exists paid_with text;

create table if not exists maintenance_parts (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  order_id bigint not null references maintenance_orders(id) on delete cascade,
  position int not null default 0,
  name text not null,
  part_number text,
  quantity numeric(10,2) not null default 1,
  unit_price numeric(12,2),
  created_at timestamptz not null default now()
);
create index if not exists maintenance_parts_idx on maintenance_parts (order_id, position);

create table if not exists maintenance_files (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  order_id bigint not null references maintenance_orders(id) on delete cascade,
  name text not null,
  path text not null,
  content_type text not null,
  bytes int,
  uploaded_by int references users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists maintenance_files_idx on maintenance_files (order_id, created_at);

do $$
declare tenant text;
begin
  foreach tenant in array array['maintenance_parts', 'maintenance_files'] loop
    execute format('alter table %I enable row level security', tenant);
    execute format('alter table %I force row level security', tenant);
    execute format('drop policy if exists company_lock on %I', tenant);
    execute format(
      'create policy company_lock on %I using (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int) '
      'with check (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int)', tenant);
  end loop;
end $$;

alter table trucks add column if not exists location_source text;
alter table trucks add column if not exists driver_source text;
update trucks set driver_source = 'samsara' where driver_source is null and driver_id is not null and driver_from_name;
update trucks t set driver_source = 'horizon' where driver_source is null and driver_id is not null
  and exists (select 1 from driver_links l where l.driver_id = t.driver_id and l.provider = 'horizoneld');
update trucks t set location_source = 'samsara' where location_source is null and latitude is not null
  and exists (select 1 from vehicle_links v where v.truck_id = t.id and v.provider = 'samsara');
update trucks t set location_source = 'horizon' where location_source is null and latitude is not null
  and exists (select 1 from vehicle_links v where v.truck_id = t.id and v.provider = 'horizoneld');

alter table odometer_readings drop constraint if exists odometer_readings_source_check;
alter table odometer_readings add constraint odometer_readings_source_check
  check (source in ('manual','fuel','service','telematics','correction'));

alter table companies add column if not exists billing_rate numeric(8,2);

create table if not exists invoices (
  id serial primary key,
  company_id int not null references companies(id) on delete cascade,
  number text not null unique,
  period date not null,
  truck_count int not null,
  unit_price numeric(8,2) not null,
  minimum numeric(8,2) not null default 0,
  amount numeric(10,2) not null,
  status text not null default 'due' check (status in ('due','paid')),
  issued_on date not null default current_date,
  due_on date not null,
  paid_at timestamptz,
  paid_by int references users(id) on delete set null,
  paid_note text,
  created_at timestamptz not null default now(),
  unique (company_id, period)
);

do $$
begin
  execute 'alter table invoices enable row level security';
  execute 'alter table invoices force row level security';
  execute 'drop policy if exists company_lock on invoices';
  execute 'create policy company_lock on invoices using (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
          'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int) '
          'with check (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
          'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int)';
end $$;

create table if not exists pm_list (
  company_id int not null references companies(id) on delete cascade,
  kind text not null,
  label text,
  removed boolean not null default false,
  created_at timestamptz not null default now(),
  primary key (company_id, kind)
);
alter table pm_list enable row level security;
alter table pm_list force row level security;
drop policy if exists company_lock on pm_list;
create policy company_lock on pm_list
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

create table if not exists truck_services (
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  kind text not null,
  removed boolean not null default false,
  miles int,
  months int,
  created_at timestamptz not null default now(),
  primary key (truck_id, kind)
);
alter table truck_services enable row level security;
alter table truck_services force row level security;
drop policy if exists company_lock on truck_services;
create policy company_lock on truck_services
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

alter table cat_notes add column if not exists href text;
alter table cat_notes add column if not exists company_id int references companies(id) on delete cascade;
alter table reminders add column if not exists noted_at timestamptz;

create table if not exists contact_requests (
  id bigserial primary key,
  name text not null,
  company text,
  trucks text,
  reach text not null,
  message text,
  ip text,
  created_at timestamptz not null default now()
);


alter table trucks add column if not exists fuel_percent numeric(5,1);
alter table trucks add column if not exists fuel_percent_at timestamptz;
alter table trucks add column if not exists tank_gallons int not null default 200;
alter table trucks add column if not exists heading int;
alter table trucks add column if not exists speed_mph numeric(5,1);

alter table companies add column if not exists fuel_assistant_enabled boolean not null default false;
alter table companies add column if not exists fuel_alert_percent int not null default 35;
alter table companies add column if not exists fuel_search_miles int not null default 150;
alter table companies add column if not exists fuel_reserve_percent int not null default 10;
alter table companies add column if not exists fuel_report_weekday int not null default 1;
alter table companies add column if not exists fuel_report_hour int not null default 8;
alter table companies add column if not exists fuel_default_mpg numeric(4,2) not null default 6.5;

create table if not exists truck_positions (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  latitude numeric(9,6) not null,
  longitude numeric(9,6) not null,
  heading int,
  speed_mph numeric(5,1),
  odometer int,
  fuel_percent numeric(5,1),
  recorded_at timestamptz not null,
  unique (truck_id, recorded_at)
);
create index if not exists truck_positions_truck_idx on truck_positions (truck_id, recorded_at desc);

create table if not exists fuel_stations (
  id serial primary key,
  key text not null unique,
  osm_id text,
  name text not null,
  brand text,
  latitude numeric(9,6),
  longitude numeric(9,6),
  address text,
  city text,
  state text,
  amenities jsonb not null default '{}',
  located_by text,
  source text not null default 'osm' check (source in ('osm', 'transaction', 'manual')),
  updated_at timestamptz not null default now()
);
create index if not exists fuel_stations_geo_idx on fuel_stations (latitude, longitude);

create table if not exists fuel_prices (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  station_id int not null references fuel_stations(id) on delete cascade,
  fuel_type text not null default 'diesel',
  retail_ppu numeric(8,4),
  net_ppu numeric(8,4) not null,
  observed_at timestamptz not null,
  source text not null default 'transaction' check (source in ('transaction', 'price_file', 'manual')),
  transaction_id bigint references fuel_transactions(id) on delete cascade,
  unique (company_id, station_id, fuel_type, observed_at, source)
);
create index if not exists fuel_prices_lookup_idx on fuel_prices (company_id, station_id, fuel_type, observed_at desc);

alter table fuel_transactions add column if not exists station_id int references fuel_stations(id) on delete set null;
alter table fuel_transactions add column if not exists retail_ppu numeric(8,4);
alter table fuel_transactions add column if not exists net_ppu numeric(8,4);
alter table fuel_transactions add column if not exists discount_ppu numeric(8,4);
alter table fuel_transactions add column if not exists best_station_id int references fuel_stations(id) on delete set null;
alter table fuel_transactions add column if not exists best_net_ppu numeric(8,4);
alter table fuel_transactions add column if not exists best_miles numeric(6,1);
alter table fuel_transactions add column if not exists missed_usd numeric(10,2);
alter table fuel_transactions add column if not exists checked_at timestamptz;
alter table fuel_transactions add column if not exists offer_id bigint;

create table if not exists fuel_offers (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  driver_id int references drivers(id) on delete set null,
  chat_id bigint,
  message_id bigint,
  reason text not null default 'low' check (reason in ('low', 'asked', 'test')),
  fuel_percent numeric(5,1),
  range_miles int,
  latitude numeric(9,6),
  longitude numeric(9,6),
  options jsonb not null default '[]',
  status text not null default 'sent' check (status in ('sent', 'accepted', 'skipped', 'expired', 'fueled', 'failed')),
  chosen_station_id int references fuel_stations(id) on delete set null,
  skip_reason text,
  answered_by bigint,
  answered_at timestamptz,
  transaction_id bigint references fuel_transactions(id) on delete set null,
  followed boolean,
  saved_usd numeric(10,2),
  created_at timestamptz not null default now()
);
create index if not exists fuel_offers_truck_idx on fuel_offers (truck_id, created_at desc);

create table if not exists driver_fuel_prefs (
  driver_id int primary key references drivers(id) on delete cascade,
  company_id int not null references companies(id) on delete cascade,
  brands_liked text[] not null default '{}',
  brands_avoided text[] not null default '{}',
  stations_avoided int[] not null default '{}',
  needs text[] not null default '{}',
  alert_percent int,
  learned jsonb not null default '{}',
  updated_at timestamptz not null default now()
);

create table if not exists fuel_reports (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  kind text not null check (kind in ('driver', 'fleet')),
  target_id int not null default 0,
  week_start date not null,
  ok boolean not null default false,
  sent_at timestamptz not null default now(),
  unique (company_id, kind, target_id, week_start)
);

do $$
declare
  tenant text;
begin
  foreach tenant in array array['truck_positions', 'fuel_prices', 'fuel_offers', 'driver_fuel_prefs', 'fuel_reports'] loop
    execute format('alter table %I enable row level security', tenant);
    execute format('alter table %I force row level security', tenant);
    execute format('drop policy if exists company_lock on %I', tenant);
    execute format(
      'create policy company_lock on %I using (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int) '
      'with check (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int)', tenant);
  end loop;
end $$;

alter table fuel_stations drop constraint if exists fuel_stations_source_check;
alter table fuel_stations add constraint fuel_stations_source_check check (source in ('osm', 'transaction', 'manual', 'brand'));

create table if not exists station_retail_prices (
  station_id int not null references fuel_stations(id) on delete cascade,
  fuel_type text not null default 'diesel',
  retail_ppu numeric(8,4) not null,
  cash_ppu numeric(8,4),
  changed_at timestamptz,
  fetched_at timestamptz not null default now(),
  source text not null,
  primary key (station_id, fuel_type)
);

create table if not exists brand_fetches (
  id bigserial primary key,
  brand text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  pages int not null default 0,
  prices int not null default 0,
  failed int not null default 0
);

create table if not exists trips (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  driver_id int references drivers(id) on delete set null,
  load_number text,
  rate numeric(12,2),
  source_text text,
  stops jsonb not null default '[]',
  route jsonb,
  distance_miles numeric(8,1),
  empty_miles numeric(8,1),
  drive_hours numeric(6,2),
  start_latitude numeric(9,6),
  start_longitude numeric(9,6),
  start_fuel_percent numeric(5,1),
  tank_gallons int,
  mpg numeric(4,2),
  plan jsonb not null default '{}',
  status text not null default 'draft' check (status in ('draft', 'sent', 'accepted', 'declined', 'done', 'cancelled')),
  chat_id bigint,
  message_id bigint,
  answer_note text,
  answered_at timestamptz,
  sent_at timestamptz,
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists trips_company_idx on trips (company_id, created_at desc);
alter table trips enable row level security;
alter table trips force row level security;
drop policy if exists company_lock on trips;
create policy company_lock on trips
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

create table if not exists fuel_refuels (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  started_at timestamptz not null,
  detected_at timestamptz not null default now(),
  from_percent numeric(5,1),
  to_percent numeric(5,1),
  gallons numeric(7,1),
  latitude numeric(9,6),
  longitude numeric(9,6),
  station_id int references fuel_stations(id) on delete set null,
  trip_id bigint references trips(id) on delete set null,
  planned boolean,
  message_id bigint,
  unique (truck_id, started_at)
);
alter table fuel_refuels enable row level security;
alter table fuel_refuels force row level security;
drop policy if exists company_lock on fuel_refuels;
create policy company_lock on fuel_refuels
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

alter table fuel_transactions add column if not exists fraud_checked_at timestamptz;

create table if not exists fuel_alerts (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int references trucks(id) on delete cascade,
  driver_id int references drivers(id) on delete set null,
  transaction_id bigint references fuel_transactions(id) on delete cascade,
  kind text not null check (kind in ('not_in_tank', 'away_from_truck', 'over_capacity', 'double_fill', 'tank_drop')),
  severity text not null default 'warn' check (severity in ('warn', 'high')),
  happened_at timestamptz not null,
  summary text not null,
  details jsonb not null default '{}',
  notified_at timestamptz,
  status text not null default 'open' check (status in ('open', 'ok', 'confirmed')),
  reviewed_by int references users(id) on delete set null,
  reviewed_at timestamptz,
  note text,
  created_at timestamptz not null default now(),
  unique (company_id, kind, transaction_id),
  unique (truck_id, kind, happened_at)
);
create index if not exists fuel_alerts_company_idx on fuel_alerts (company_id, created_at desc);
alter table fuel_alerts enable row level security;
alter table fuel_alerts force row level security;
drop policy if exists company_lock on fuel_alerts;
create policy company_lock on fuel_alerts
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

alter table fuel_transactions drop constraint if exists fuel_transactions_source_check;
alter table fuel_transactions add constraint fuel_transactions_source_check check (source in ('manual', 'import', 'api', 'demo'));

alter table trips add column if not exists share_token text;
create unique index if not exists trips_share_token_idx on trips (share_token);
alter table trips add column if not exists source text not null default 'web';
alter table companies add column if not exists trips_from_group boolean not null default false;

create table if not exists regional_diesel_prices (
  region text not null,
  week date not null,
  price numeric(6,3) not null,
  fetched_at timestamptz not null default now(),
  primary key (region, week)
);

create table if not exists state_diesel_daily (
  day date not null,
  state text not null,
  stations int not null,
  avg_price numeric(6,3) not null,
  min_price numeric(6,3) not null,
  max_price numeric(6,3) not null,
  cheapest_station_id int references fuel_stations(id) on delete set null,
  primary key (day, state)
);

alter table trucks add column if not exists health jsonb;
alter table trucks add column if not exists health_at timestamptz;

create table if not exists health_alerts (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  kind text not null,
  value numeric,
  detail text,
  fault_id bigint references fault_events(id) on delete set null,
  opened_at timestamptz not null default now(),
  cleared_at timestamptz,
  sent_at timestamptz
);
create unique index if not exists health_alerts_open on health_alerts (truck_id, kind) where cleared_at is null and fault_id is null;
create unique index if not exists health_alerts_fault on health_alerts (fault_id) where fault_id is not null;
create index if not exists health_alerts_company on health_alerts (company_id, opened_at desc);

create table if not exists safety_events (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int references trucks(id) on delete set null,
  driver_id int references drivers(id) on delete set null,
  external_id text not null,
  kind text not null,
  label text,
  severity text,
  happened_at timestamptz not null,
  ended_at timestamptz,
  speed_mph numeric,
  limit_mph numeric,
  g_force numeric,
  latitude numeric(9,6),
  longitude numeric(9,6),
  place text,
  raw jsonb,
  alerted_at timestamptz,
  created_at timestamptz not null default now(),
  unique (company_id, external_id)
);
create index if not exists safety_events_company on safety_events (company_id, happened_at desc);
create index if not exists safety_events_driver on safety_events (driver_id, happened_at desc);

create table if not exists mpg_checks (
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  day date not null,
  recent_mpg numeric,
  recent_miles numeric,
  base_mpg numeric,
  base_miles numeric,
  primary key (truck_id, day)
);

create table if not exists documents (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  owner text not null check (owner in ('driver', 'truck', 'trailer', 'company')),
  driver_id int references drivers(id) on delete cascade,
  truck_id int references trucks(id) on delete cascade,
  trailer_id int,
  kind text not null,
  title text,
  number text,
  state text,
  issued_on date,
  expires_on date,
  file_path text,
  file_name text,
  content_type text,
  note text,
  notified_stage int,
  created_by int references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists documents_company on documents (company_id, expires_on);
create index if not exists documents_driver on documents (driver_id);
create index if not exists documents_truck on documents (truck_id);

insert into documents (company_id, owner, driver_id, kind, expires_on)
select d.company_id, 'driver', d.id, 'cdl', d.license_expires from drivers d
where d.license_expires is not null and not exists (select 1 from documents x where x.driver_id = d.id and x.kind = 'cdl');
insert into documents (company_id, owner, driver_id, kind, expires_on)
select d.company_id, 'driver', d.id, 'medical', d.medical_expires from drivers d
where d.medical_expires is not null and not exists (select 1 from documents x where x.driver_id = d.id and x.kind = 'medical');
insert into documents (company_id, owner, truck_id, kind, expires_on)
select t.company_id, 'truck', t.id, 'registration', t.registration_expires from trucks t
where t.registration_expires is not null and not exists (select 1 from documents x where x.truck_id = t.id and x.kind = 'registration');
insert into documents (company_id, owner, truck_id, kind, expires_on)
select t.company_id, 'truck', t.id, 'insurance', t.insurance_expires from trucks t
where t.insurance_expires is not null and not exists (select 1 from documents x where x.truck_id = t.id and x.kind = 'insurance');

create table if not exists trailers (
  id serial primary key,
  company_id int not null references companies(id) on delete cascade,
  unit_number text not null,
  kind text not null default 'dry_van',
  vin text,
  plate text,
  plate_state text,
  year int,
  make text,
  length_ft int,
  status text not null default 'active',
  truck_id int references trucks(id) on delete set null,
  external_id text,
  latitude numeric(9,6),
  longitude numeric(9,6),
  located_at timestamptz,
  location text,
  annual_inspection_on date,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (company_id, unit_number)
);
do $$ begin
  alter table documents add constraint documents_trailer_fk foreign key (trailer_id) references trailers(id) on delete cascade;
exception when duplicate_object then null; end $$;

alter table companies add column if not exists home_address text;
alter table companies add column if not exists home_latitude numeric(9,6);
alter table companies add column if not exists home_longitude numeric(9,6);

alter table maintenance_orders add column if not exists shop_rating smallint check (shop_rating between 1 and 5);
alter table maintenance_orders add column if not exists shop_comment text;

alter table companies add column if not exists document_alerts_enabled boolean not null default false;

create table if not exists alert_groups (
  company_id int primary key references companies(id) on delete cascade,
  chat_id bigint not null,
  linked_by int references users(id) on delete set null,
  linked_at timestamptz not null default now(),
  backfilled_at timestamptz
);
create index if not exists alert_groups_chat on alert_groups (chat_id);
alter table alert_groups enable row level security;
alter table alert_groups force row level security;
drop policy if exists company_lock on alert_groups;
create policy company_lock on alert_groups
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

create table if not exists alert_topics (
  chat_id bigint not null,
  topic text not null,
  thread_id bigint not null,
  created_at timestamptz not null default now(),
  primary key (chat_id, topic)
);
alter table companies add column if not exists alerts_group boolean not null default false;
alter table safety_events add column if not exists video_sent_at timestamptz;

alter table maintenance_orders add column if not exists priority text not null default 'medium';
alter table maintenance_orders add column if not exists reported_at timestamptz;
update maintenance_orders set reported_at = created_at where reported_at is null;
alter table maintenance_orders alter column reported_at set default now();
alter table maintenance_orders alter column reported_at set not null;
alter table maintenance_orders add column if not exists breakdown boolean not null default false;
alter table maintenance_orders add column if not exists location text;
alter table maintenance_orders add column if not exists latitude numeric(9,6);
alter table maintenance_orders add column if not exists longitude numeric(9,6);
alter table maintenance_orders add column if not exists cause text;
alter table maintenance_orders add column if not exists resolution text;
alter table maintenance_orders add column if not exists load_number text;
alter table maintenance_orders add column if not exists towing_cost numeric(12,2);
alter table maintenance_orders add column if not exists resolved_at timestamptz;
alter table maintenance_orders add column if not exists from_breakdown_id bigint unique;
alter table maintenance_orders drop constraint if exists maintenance_orders_status_check;
alter table maintenance_orders add constraint maintenance_orders_status_check
  check (status in ('open','scheduled','towing','in_shop','in_progress','done','cancelled'));
alter table maintenance_orders drop constraint if exists maintenance_orders_priority_check;
alter table maintenance_orders add constraint maintenance_orders_priority_check
  check (priority in ('low','medium','high','urgent'));
create index if not exists maint_reported_idx on maintenance_orders (company_id, reported_at desc);

create table if not exists work_order_comments (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  order_id bigint not null references maintenance_orders(id) on delete cascade,
  kind text not null default 'comment' check (kind in ('comment','status','event')),
  body text,
  file_path text,
  file_name text,
  content_type text,
  file_bytes int,
  created_by int references users(id) on delete set null,
  author_name text,
  created_at timestamptz not null default now()
);
create index if not exists work_order_comments_idx on work_order_comments (order_id, created_at, id);
alter table work_order_comments enable row level security;
alter table work_order_comments force row level security;
drop policy if exists company_lock on work_order_comments;
create policy company_lock on work_order_comments
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

do $$
declare
  b record;
  target bigint;
  new_status text;
begin
  for b in select * from breakdowns x
           where not exists (select 1 from maintenance_orders m where m.from_breakdown_id = x.id)
           order by x.id loop
    new_status := case b.status when 'resolved' then 'done' else b.status end;
    select id into target from maintenance_orders
     where breakdown_id = b.id and from_breakdown_id is null and company_id = b.company_id
     order by id limit 1;
    if target is not null then
      update maintenance_orders set
        breakdown = true, from_breakdown_id = b.id, priority = b.severity,
        reported_at = least(reported_at, b.occurred_at),
        driver_id = coalesce(driver_id, b.driver_id),
        location = coalesce(location, b.location), latitude = coalesce(latitude, b.latitude),
        longitude = coalesce(longitude, b.longitude), cause = coalesce(cause, b.cause),
        resolution = coalesce(resolution, b.resolution), load_number = coalesce(load_number, b.load_number),
        towing_cost = coalesce(towing_cost, b.towing_cost), resolved_at = coalesce(resolved_at, b.resolved_at),
        description = case when description like 'Repair from breakdown #%' then
          b.description || E'\n' || regexp_replace(description, '^Repair from breakdown #[0-9]+: ', 'Repair: ')
          else description end
      where id = target;
    else
      insert into maintenance_orders (company_id, truck_id, driver_id, kind, status, priority, reported_at,
          performed_on, cost, description, breakdown, location, latitude, longitude, cause, resolution,
          load_number, towing_cost, resolved_at, from_breakdown_id, breakdown_id, created_by, created_at, updated_at)
      values (b.company_id, b.truck_id, b.driver_id, 'repair', new_status, b.severity, b.occurred_at,
          b.resolved_at::date, b.repair_cost, b.description, true, b.location, b.latitude, b.longitude,
          b.cause, b.resolution, b.load_number, b.towing_cost, b.resolved_at, b.id, b.id, b.created_by,
          b.created_at, b.updated_at)
      returning id into target;
    end if;
    insert into work_order_comments (company_id, order_id, kind, body, created_by, author_name, created_at)
    values (b.company_id, target, 'event', 'reported this as case #' || b.id, b.created_by,
            (select name from users where id = b.created_by), b.occurred_at);
    insert into work_order_comments (company_id, order_id, kind, body, created_by, author_name, created_at)
    select u.company_id, target, case when u.status is not null and u.note like 'Status changed to %' then 'status' else 'comment' end,
           case when u.status is not null and u.note like 'Status changed to %'
                then 'changed status to ' || replace(case u.status when 'resolved' then 'done' else u.status end, '_', ' ')
                else u.note end,
           u.created_by, (select name from users where id = u.created_by), u.created_at
      from breakdown_updates u where u.breakdown_id = b.id order by u.created_at;
    update reminders set entity = 'maintenance_order', entity_id = target where entity = 'breakdown' and entity_id = b.id;
  end loop;
end $$;

alter table maintenance_orders alter column truck_id drop not null;
alter table maintenance_orders add column if not exists asset_type text not null default 'truck';
alter table maintenance_orders add column if not exists trailer_id int references trailers(id) on delete cascade;
alter table maintenance_orders drop constraint if exists maintenance_orders_asset_check;
alter table maintenance_orders add constraint maintenance_orders_asset_check
  check ((asset_type = 'truck' and truck_id is not null) or (asset_type = 'trailer' and trailer_id is not null));
create index if not exists maint_trailer_idx on maintenance_orders (trailer_id, performed_on desc);

create table if not exists driver_assignments (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  driver_id int not null references drivers(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  source text not null default 'assigned'
);
create index if not exists driver_assignments_driver_idx on driver_assignments (driver_id, started_at desc);
create index if not exists driver_assignments_truck_idx on driver_assignments (truck_id, started_at desc);
alter table driver_assignments enable row level security;
alter table driver_assignments force row level security;
drop policy if exists company_lock on driver_assignments;
create policy company_lock on driver_assignments
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

create or replace function track_driver_assignment() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' and new.driver_id is not distinct from old.driver_id then
    return new;
  end if;
  if tg_op = 'UPDATE' and old.driver_id is not null then
    update driver_assignments set ended_at = now()
     where truck_id = new.id and driver_id = old.driver_id and ended_at is null;
  end if;
  if new.driver_id is not null then
    insert into driver_assignments (company_id, driver_id, truck_id, started_at)
    select new.company_id, new.driver_id, new.id, now()
     where not exists (select 1 from driver_assignments a
                        where a.truck_id = new.id and a.driver_id = new.driver_id and a.ended_at is null);
  end if;
  return new;
end $$;
drop trigger if exists trucks_driver_assignment on trucks;
create trigger trucks_driver_assignment after insert or update of driver_id on trucks
  for each row execute function track_driver_assignment();

do $$ begin
  if not exists (select 1 from driver_assignments) then
    insert into driver_assignments (company_id, driver_id, truck_id, started_at, ended_at, source)
    select company_id, driver_id, truck_id, min(at), max(at), 'history' from (
      select company_id, driver_id, truck_id, happened_at as at from safety_events where driver_id is not null and truck_id is not null
      union all select company_id, driver_id, truck_id, purchased_at from fuel_transactions where driver_id is not null
      union all select company_id, driver_id, truck_id, submitted_at from inspections where driver_id is not null and truck_id is not null
    ) seen group by company_id, driver_id, truck_id;
    insert into driver_assignments (company_id, driver_id, truck_id, started_at, source)
    select t.company_id, t.driver_id, t.id, coalesce(t.updated_at, now()), 'assigned' from trucks t where t.driver_id is not null;
  end if;
end $$;

alter table health_alerts add column if not exists driver_id int references drivers(id) on delete set null;
create index if not exists health_alerts_driver_idx on health_alerts (driver_id, opened_at desc);
update health_alerts a set driver_id = t.driver_id from trucks t
 where a.truck_id = t.id and a.driver_id is null and a.kind like 'hos%' and t.driver_id is not null;

create table if not exists engine_sessions (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  driver_id int references drivers(id) on delete set null,
  state text not null,
  started_at timestamptz not null,
  ended_at timestamptz,
  latitude numeric(9,6),
  longitude numeric(9,6),
  location text
);
create index if not exists engine_sessions_truck_idx on engine_sessions (truck_id, started_at desc);
create index if not exists engine_sessions_driver_idx on engine_sessions (driver_id, state, started_at desc);
create unique index if not exists engine_sessions_open_idx on engine_sessions (truck_id) where ended_at is null;
alter table engine_sessions enable row level security;
alter table engine_sessions force row level security;
drop policy if exists company_lock on engine_sessions;
create policy company_lock on engine_sessions
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

alter table trucks add column if not exists carrier_group text;
alter table trucks add column if not exists unit_label text;
update trucks set carrier_group = nullif(trim(substring(unit_number from '[\(\[]\s*([^\)\]]+?)\s*[\)\]]')), '')
 where carrier_group is null and unit_number ~ '[\(\[]';
update trucks t set unit_number = substring(t.unit_number from '^\s*([0-9]+[A-Za-z]?)(\s|\(|\[|$)'), updated_at = now()
 where t.unit_number ~ '^\s*[0-9]+[A-Za-z]?\s*[\s\(\[]\s*\S'
   and not exists (select 1 from trucks o where o.company_id = t.company_id and o.id <> t.id
                   and lower(o.unit_number) = lower(substring(t.unit_number from '^\s*([0-9]+[A-Za-z]?)(\s|\(|\[|$)')));
create index if not exists trucks_group_idx on trucks (company_id, carrier_group);

create or replace function tidy_driver_name() returns trigger language plpgsql as $$
begin
  new.name := regexp_replace(trim(new.name), '\s+', ' ', 'g');
  if new.name = upper(new.name) or new.name = lower(new.name) then
    new.name := initcap(new.name);
  end if;
  return new;
end $$;
drop trigger if exists drivers_tidy_name on drivers;
create trigger drivers_tidy_name before insert or update of name on drivers
  for each row execute function tidy_driver_name();
update drivers set name = name where name = upper(name) or name = lower(name) or name ~ '\s\s' or name <> trim(name);

create table if not exists place_suggestions (
  query text primary key,
  results jsonb not null default '[]',
  fetched_at timestamptz not null default now()
);

alter table driver_links add column if not exists ignored boolean not null default false;

alter table drivers add column if not exists name_locked boolean not null default false;

alter table companies add column if not exists speeding_min_over int not null default 10;
alter table companies add column if not exists speeding_min_seconds int not null default 30;
alter table safety_events add column if not exists status text not null default 'open';
alter table safety_events add column if not exists acknowledged_at timestamptz;
alter table safety_events add column if not exists acknowledged_by int references users(id) on delete set null;
alter table safety_events add column if not exists cleared_at timestamptz;
alter table safety_events add column if not exists cleared_by int references users(id) on delete set null;
alter table health_alerts add column if not exists acknowledged_at timestamptz;
alter table health_alerts add column if not exists acknowledged_by int references users(id) on delete set null;
alter table health_alerts add column if not exists cleared_by int references users(id) on delete set null;
alter table fuel_alerts add column if not exists acknowledged_at timestamptz;
alter table fuel_alerts add column if not exists acknowledged_by int references users(id) on delete set null;
do $$ begin
  if not exists (select 1 from safety_events where status <> 'open' or cleared_at is not null) then
    update safety_events set status = 'cleared', cleared_at = now() where happened_at < now() - interval '7 days';
  end if;
end $$;
create index if not exists safety_events_status_idx on safety_events (company_id, status, happened_at desc);

alter table companies add column if not exists comeback_days int not null default 60;
create table if not exists maintenance_comebacks (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  order_id bigint not null references maintenance_orders(id) on delete cascade,
  earlier_id bigint not null references maintenance_orders(id) on delete cascade,
  reason text not null,
  created_at timestamptz not null default now(),
  dismissed_at timestamptz,
  dismissed_by int references users(id) on delete set null,
  unique (order_id, earlier_id)
);
create index if not exists maintenance_comebacks_order_idx on maintenance_comebacks (order_id);
create index if not exists maintenance_comebacks_earlier_idx on maintenance_comebacks (earlier_id);
alter table maintenance_comebacks enable row level security;
alter table maintenance_comebacks force row level security;
drop policy if exists company_lock on maintenance_comebacks;
create policy company_lock on maintenance_comebacks
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

alter table maintenance_orders add column if not exists down_started_at timestamptz;
alter table maintenance_orders add column if not exists down_ended_at timestamptz;
alter table maintenance_orders add column if not exists down_end_reason text;
update maintenance_orders m set down_started_at = coalesce(
    (select min(c.created_at) from work_order_comments c where c.order_id = m.id and c.kind = 'status'
       and (c.body like '%to in shop' or c.body like '%to towing')),
    case when m.breakdown then m.reported_at end)
 where m.down_started_at is null and (m.breakdown or exists (select 1 from work_order_comments c where c.order_id = m.id
       and c.kind = 'status' and (c.body like '%to in shop' or c.body like '%to towing')));
update maintenance_orders set down_ended_at = coalesce(resolved_at, updated_at), down_end_reason = status
 where down_started_at is not null and down_ended_at is null and status in ('done', 'cancelled');
update maintenance_orders m set down_ended_at = mv.at, down_end_reason = 'moving'
  from (select m2.id, (select min(p.recorded_at) from truck_positions p where p.truck_id = m2.truck_id and p.speed_mph >= 5
                       and p.recorded_at > m2.down_started_at + interval '30 minutes') as at
          from maintenance_orders m2 where m2.down_started_at is not null and m2.asset_type = 'truck') mv
 where mv.id = m.id and mv.at is not null and mv.at < coalesce(m.down_ended_at, 'infinity') and m.down_end_reason is distinct from 'moving';

create table if not exists recall_campaigns (
  campaign text primary key,
  manufacturer text,
  make text,
  model text,
  model_year int,
  component text,
  summary text,
  consequence text,
  remedy text,
  notes text,
  report_date date,
  park_it boolean not null default false,
  first_seen_at timestamptz not null default now(),
  fetched_at timestamptz not null default now()
);
create table if not exists vehicle_recalls (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  truck_id int references trucks(id) on delete cascade,
  trailer_id int references trailers(id) on delete cascade,
  campaign text not null references recall_campaigns(campaign) on delete cascade,
  status text not null default 'open' check (status in ('open', 'done', 'not_applicable')),
  done_on date,
  done_shop text,
  work_order_id bigint references maintenance_orders(id) on delete set null,
  first_seen_at timestamptz not null default now(),
  updated_by int references users(id) on delete set null,
  updated_at timestamptz not null default now(),
  check (truck_id is not null or trailer_id is not null)
);
create unique index if not exists vehicle_recalls_truck_key on vehicle_recalls (truck_id, campaign) where truck_id is not null;
create unique index if not exists vehicle_recalls_trailer_key on vehicle_recalls (trailer_id, campaign) where trailer_id is not null;
create index if not exists vehicle_recalls_company_idx on vehicle_recalls (company_id, status);
alter table vehicle_recalls enable row level security;
alter table vehicle_recalls force row level security;
drop policy if exists company_lock on vehicle_recalls;
create policy company_lock on vehicle_recalls
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);
create table if not exists recall_checks (
  id bigserial primary key,
  ran_at timestamptz not null default now(),
  vehicles int,
  lookups int,
  new_campaigns int,
  linked int
);

create table if not exists weather_zones (
  zone_id text primary key,
  name text,
  state text,
  geometry jsonb,
  bbox numeric[],
  fetched_at timestamptz not null default now()
);
create table if not exists weather_alerts (
  id text primary key,
  event text not null,
  severity text,
  headline text,
  description text,
  instruction text,
  area text,
  states text[],
  onset timestamptz,
  expires timestamptz,
  ends timestamptz,
  zones text[],
  geometry jsonb,
  bbox numeric[],
  active boolean not null default true,
  fetched_at timestamptz not null default now()
);
create table if not exists truck_weather (
  truck_id int not null references trucks(id) on delete cascade,
  alert_id text not null references weather_alerts(id) on delete cascade,
  company_id int not null references companies(id) on delete cascade,
  since timestamptz not null default now(),
  primary key (truck_id, alert_id)
);
alter table truck_weather enable row level security;
alter table truck_weather force row level security;
drop policy if exists company_lock on truck_weather;
create policy company_lock on truck_weather
  using (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = ''
    or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

create table if not exists ai_conversations (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  user_id int references users(id) on delete cascade,
  title text not null default 'New chat',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists ai_conversations_user_idx on ai_conversations (company_id, user_id, updated_at desc);
alter table ai_chats add column if not exists conversation_id bigint references ai_conversations(id) on delete cascade;
create index if not exists ai_chats_conversation_idx on ai_chats (conversation_id, created_at, id);
create table if not exists ai_chat_files (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  chat_id bigint not null references ai_chats(id) on delete cascade,
  file_path text not null,
  file_name text not null,
  content_type text not null,
  file_bytes int,
  created_at timestamptz not null default now()
);
create index if not exists ai_chat_files_chat_idx on ai_chat_files (chat_id);
do $$
declare
  tenant text;
begin
  foreach tenant in array array['ai_conversations', 'ai_chat_files'] loop
    execute format('alter table %I enable row level security', tenant);
    execute format('alter table %I force row level security', tenant);
    execute format('drop policy if exists company_lock on %I', tenant);
    execute format(
      'create policy company_lock on %I using (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int) '
      'with check (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
      'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int)', tenant);
  end loop;
end $$;
do $$
declare
  g record;
  conv bigint;
begin
  for g in select c.company_id, c.user_id, c.truck_id, min(c.created_at) as first_at, max(c.created_at) as last_at
           from ai_chats c where c.conversation_id is null group by 1, 2, 3 loop
    insert into ai_conversations (company_id, user_id, title, created_at, updated_at)
    values (g.company_id, g.user_id,
            coalesce('Unit ' || (select unit_number from trucks where id = g.truck_id), 'Chat'),
            g.first_at, g.last_at)
    returning id into conv;
    update ai_chats set conversation_id = conv
     where conversation_id is null and company_id = g.company_id
       and user_id is not distinct from g.user_id and truck_id is not distinct from g.truck_id;
  end loop;
end $$;

create table if not exists efs_network (
  id bigserial primary key,
  company_id int not null references companies(id) on delete cascade,
  name text not null,
  address text,
  city text,
  state text,
  zip text,
  latitude numeric(9,6),
  longitude numeric(9,6),
  station_ids int[] not null default '{}',
  checked_at timestamptz,
  uploaded_at timestamptz not null default now()
);
create index if not exists efs_network_company_idx on efs_network (company_id);
alter table efs_network enable row level security;
alter table efs_network force row level security;
drop policy if exists company_lock on efs_network;
create policy company_lock on efs_network
  using (coalesce(current_setting('kaido.company_id', true), '') = '' or company_id = nullif(current_setting('kaido.company_id', true), '')::int)
  with check (coalesce(current_setting('kaido.company_id', true), '') = '' or company_id = nullif(current_setting('kaido.company_id', true), '')::int);

alter table fuel_offers drop constraint if exists fuel_offers_reason_check;
alter table fuel_offers add constraint fuel_offers_reason_check check (reason in ('low', 'asked', 'test', 'office'));
alter table fuel_offers drop constraint if exists fuel_offers_status_check;
alter table fuel_offers add constraint fuel_offers_status_check check (status in ('ready', 'sent', 'accepted', 'skipped', 'expired', 'fueled', 'failed'));

alter table maintenance_orders add column if not exists resolved_by int references users(id) on delete set null;
update maintenance_orders m set resolved_by = coalesce((select c.created_by from work_order_comments c
    where c.order_id = m.id and c.kind = 'status' and c.body like '% to done' and c.created_by is not null
    order by c.created_at desc, c.id desc limit 1), m.created_by)
  where m.status = 'done' and m.resolved_by is null;

alter table companies add column if not exists safety_all boolean not null default false;
update companies set safety_all = true where name = 'DFK transportation' and not safety_all;

alter table companies add column if not exists walkaround_steps jsonb;
alter table inspections add column if not exists mode text not null default 'form';
alter table inspections add column if not exists media_flags text[] not null default '{}';
alter table inspections add column if not exists gps_lat double precision;
alter table inspections add column if not exists gps_lon double precision;
alter table inspections add column if not exists gps_miles numeric(8,2);
alter table inspections add column if not exists started_at timestamptz;
alter table inspections add column if not exists voice_text text;
alter table inspections add column if not exists lang text;
alter table inspection_photos add column if not exists step text;
alter table inspection_photos add column if not exists taken_at timestamptz;
alter table inspection_photos add column if not exists latitude double precision;
alter table inspection_photos add column if not exists longitude double precision;
alter table inspection_photos add column if not exists live_check jsonb;

create table if not exists walk_sessions (
  id bigserial primary key,
  key text not null unique,
  company_id int not null references companies(id) on delete cascade,
  truck_id int not null references trucks(id) on delete cascade,
  driver_id int references drivers(id) on delete set null,
  driver_name text,
  kind text not null default 'pre_trip',
  mode text not null default 'live' check (mode in ('live', 'upload')),
  lang text,
  latitude double precision,
  longitude double precision,
  accuracy_m int,
  meta jsonb not null default '{}',
  checks int not null default 0,
  ip text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  inspection_id bigint references inspections(id) on delete set null
);
create index if not exists walk_sessions_truck_idx on walk_sessions (truck_id, started_at desc);

create table if not exists walk_frames (
  id bigserial primary key,
  session_id bigint not null references walk_sessions(id) on delete cascade,
  client_id text not null,
  step text,
  path text not null,
  content_type text not null default 'image/jpeg',
  bytes int,
  taken_at timestamptz,
  latitude double precision,
  longitude double precision,
  live_check jsonb,
  photo_id bigint references inspection_photos(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (session_id, client_id)
);

create table if not exists pti_links (
  id bigserial primary key,
  company_id integer not null references companies(id) on delete cascade,
  truck_id integer not null references trucks(id) on delete cascade,
  driver_id integer references drivers(id) on delete set null,
  driver_name text not null,
  phone text,
  token text not null unique,
  sent_ok boolean,
  sent_to text,
  created_by integer references users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists pti_links_company_idx on pti_links (company_id, created_at desc);

do $$
begin
  execute 'alter table pti_links enable row level security';
  execute 'alter table pti_links force row level security';
  execute 'drop policy if exists company_lock on pti_links';
  execute 'create policy company_lock on pti_links using (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
    'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int) '
    'with check (coalesce(current_setting(''kaido.company_id'', true), '''') = '''' '
    'or company_id = nullif(current_setting(''kaido.company_id'', true), '''')::int)';
end $$;

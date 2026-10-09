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

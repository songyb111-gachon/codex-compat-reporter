-- The advanced edition's file of version 9 as v0.6.20 creates it fresh: state/schema.py STATEMENTS, one statement
-- to a paragraph (the spend table is version 7's and 8's, byte for byte; version 9 adds the table steers, a person's
-- own words added to a running turn, and changes nothing else).
-- tests/test_report.py reads it with executescript; nothing else of the product is needed.

CREATE TABLE meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        generation INTEGER NOT NULL CHECK (generation >= 0),
        global_hourly INTEGER NOT NULL CHECK (global_hourly BETWEEN 1 AND 12)
    );

INSERT INTO meta VALUES (1, 0, 12);

CREATE TABLE arming (
        capability TEXT PRIMARY KEY,
        state TEXT NOT NULL CHECK (state IN ('off', 'shadow', 'armed')),
        since REAL NOT NULL,
        actor TEXT NOT NULL,
        reason TEXT,
        statement_revision INTEGER,
        engine_version TEXT,
        warnings TEXT CHECK (warnings IS NULL OR warnings NOT GLOB '*[^a-z_,]*')
    );

CREATE TABLE spend (
        spend_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        capability TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        interruption_id TEXT
    );

CREATE INDEX spend_at ON spend(at);

CREATE TABLE records (
        record_id TEXT PRIMARY KEY,
        capability TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('waiting', 'in_flight', 'finished', 'cancelled')),
        created_at REAL NOT NULL,
        claimed_at REAL,
        claims INTEGER NOT NULL CHECK (claims >= 0),
        finished_at REAL
    );

CREATE INDEX records_thread ON records(thread_id);

CREATE TABLE overrides (
        interruption_id TEXT NOT NULL,
        capability TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('force_once', 'early_reset', 'capacity_ladder', 'resend_once', 'queue_for_open')),
        created_at REAL NOT NULL,
        used_at REAL,
        PRIMARY KEY (interruption_id, capability)
    );

CREATE TABLE journal (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        capability TEXT,
        code TEXT NOT NULL,
        reason TEXT,
        actor TEXT,
        point TEXT,
        answer TEXT
    );

CREATE TABLE sampler (
        capability TEXT NOT NULL,
        code TEXT NOT NULL,
        day INTEGER NOT NULL,
        count INTEGER NOT NULL CHECK (count >= 0),
        PRIMARY KEY (capability, code, day)
    );

CREATE TABLE options (
        capability TEXT NOT NULL,
        choice TEXT NOT NULL,
        value INTEGER NOT NULL CHECK (typeof(value) = 'integer' AND value >= 1),
        PRIMARY KEY (capability, choice)
    );

CREATE TABLE rules (
        rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag TEXT NOT NULL CHECK (length(tag) BETWEEN 1 AND 64 AND tag GLOB '[A-Za-z]*' AND tag NOT GLOB '*[^A-Za-z0-9]*'),
        status_from INTEGER CHECK (status_from IS NULL OR (typeof(status_from) = 'integer' AND status_from BETWEEN 100 AND 599)),
        status_to INTEGER CHECK (status_to IS NULL OR (typeof(status_to) = 'integer' AND status_to BETWEEN 100 AND 599)),
        category TEXT NOT NULL CHECK (category IN ('network_transient', 'rate_limit_transient', 'server_5xx', 'stream_interrupted', 'timeout')),
        created_at REAL NOT NULL,
        CHECK ((status_from IS NULL) = (status_to IS NULL)),
        CHECK (status_from IS NULL OR status_from <= status_to)
    );

CREATE TABLE admissions (
        interruption_id TEXT PRIMARY KEY CHECK (length(interruption_id) = 64),
        capability TEXT NOT NULL,
        answer TEXT NOT NULL CHECK (answer IN ('admit', 'as_network_transient', 'as_rate_limit_transient', 'as_server_5xx', 'as_stream_interrupted', 'as_timeout', 'capacity')),
        rule_id INTEGER,
        tag TEXT CHECK (tag IS NULL OR (length(tag) BETWEEN 1 AND 64 AND tag GLOB '[A-Za-z]*' AND tag NOT GLOB '*[^A-Za-z0-9]*')),
        status INTEGER CHECK (status IS NULL OR (typeof(status) = 'integer' AND status BETWEEN 100 AND 599)),
        form TEXT CHECK (form IS NULL OR form IN ('tagged', 'status_only', 'unrecognised', 'message_only', 'absent')),
        has_words INTEGER CHECK (has_words IS NULL OR has_words IN (0, 1)),
        sampled INTEGER NOT NULL CHECK (sampled IN (0, 1)),
        created_at REAL NOT NULL
    );

CREATE INDEX admissions_created ON admissions(created_at);

CREATE TABLE samples (
        sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        tag TEXT CHECK (tag IS NULL OR (length(tag) BETWEEN 1 AND 64 AND tag GLOB '[A-Za-z]*' AND tag NOT GLOB '*[^A-Za-z0-9]*')),
        status INTEGER CHECK (status IS NULL OR (typeof(status) = 'integer' AND status BETWEEN 100 AND 599)),
        form TEXT NOT NULL CHECK (form IN ('tagged', 'status_only', 'unrecognised', 'message_only', 'absent')),
        has_words INTEGER NOT NULL CHECK (has_words IN (0, 1)),
        items_agent INTEGER CHECK (items_agent IS NULL OR (typeof(items_agent) = 'integer' AND items_agent >= 0)),
        items_command INTEGER CHECK (items_command IS NULL OR (typeof(items_command) = 'integer' AND items_command >= 0)),
        items_file INTEGER CHECK (items_file IS NULL OR (typeof(items_file) = 'integer' AND items_file >= 0)),
        items_tool INTEGER CHECK (items_tool IS NULL OR (typeof(items_tool) = 'integer' AND items_tool >= 0)),
        items_user INTEGER CHECK (items_user IS NULL OR (typeof(items_user) = 'integer' AND items_user >= 0)),
        items_other INTEGER CHECK (items_other IS NULL OR (typeof(items_other) = 'integer' AND items_other >= 0)),
        duration REAL CHECK (duration IS NULL OR duration >= 0)
    );

CREATE INDEX samples_at ON samples(at);

CREATE TABLE windows (
        bucket TEXT NOT NULL CHECK (bucket IN ('codex', 'premium', 'legacy', 'other')),
        minutes INTEGER NOT NULL CHECK (typeof(minutes) = 'integer' AND minutes >= 1 AND minutes <= 100800),
        open_reset_at INTEGER CHECK (open_reset_at IS NULL OR (typeof(open_reset_at) = 'integer' AND open_reset_at >= 0)),
        open_full INTEGER NOT NULL CHECK (open_full IN (0, 1)),
        last_closed_at INTEGER CHECK (last_closed_at IS NULL OR (typeof(last_closed_at) = 'integer' AND last_closed_at >= 0)),
        resets INTEGER NOT NULL CHECK (typeof(resets) = 'integer' AND resets >= 0),
        hits INTEGER NOT NULL CHECK (typeof(hits) = 'integer' AND hits >= 0),
        seen_at REAL,
        misses INTEGER NOT NULL CHECK (typeof(misses) = 'integer' AND misses >= 0),
        PRIMARY KEY (bucket, minutes)
    );

CREATE TABLE readings (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        read_at REAL,
        asked_at REAL,
        applied_at REAL,
        signal_at REAL,
        credits INTEGER CHECK (credits IS NULL OR (typeof(credits) = 'integer' AND credits >= 0)),
        expiry_known INTEGER CHECK (expiry_known IS NULL OR expiry_known IN (0, 1)),
        nearest_expiry INTEGER CHECK (nearest_expiry IS NULL OR (typeof(nearest_expiry) = 'integer' AND nearest_expiry >= 0))
    );

INSERT INTO readings (singleton) VALUES (1);

CREATE TABLE reset_rules (
        rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
        capability TEXT NOT NULL CHECK (capability IN ('reset_credit', 'reset_message')),
        bucket TEXT NOT NULL CHECK (bucket IN ('codex', 'premium', 'legacy', 'other')),
        minutes INTEGER NOT NULL CHECK (typeof(minutes) = 'integer' AND minutes >= 1 AND minutes <= 100800),
        ordinal INTEGER NOT NULL CHECK (typeof(ordinal) = 'integer' AND ordinal >= 0 AND ordinal <= 9),
        repeat INTEGER NOT NULL CHECK (repeat IN (0, 1)),
        ask_first INTEGER NOT NULL CHECK (ask_first IN (0, 1)),
        record_id TEXT CHECK (record_id IS NULL OR (length(record_id) = 64 AND record_id NOT GLOB '*[^0-9a-f]*')),
        words TEXT,
        created_at REAL NOT NULL,
        adopted_at REAL,
        base INTEGER CHECK (base IS NULL OR (typeof(base) = 'integer' AND base >= 0)),
        state TEXT NOT NULL CHECK (state IN ('counting', 'ready', 'held', 'done', 'cancelled')),
        reason TEXT CHECK (reason IS NULL OR reason IN ('ask_first', 'count_unknown', 'expiry_unknown', 'bound', 'no_method', 'nothing_waiting', 'count_gap', 'window_gone', 'spent', 'nothing_to_reset', 'no_credit', 'lapsed', 'unknown', 'delivered', 'expired', 'not_started', 'by_person', 'turned_off', 'conversation_off', 'handed_over', 'superseded', 'withdrawn', 'withdraw_refused')),
        gate TEXT CHECK (gate IS NULL OR (length(gate) BETWEEN 1 AND 48 AND gate NOT GLOB '*[^a-zA-Z0-9_]*')),
        gate_reason TEXT CHECK (gate_reason IS NULL OR (length(gate_reason) BETWEEN 1 AND 48 AND gate_reason NOT GLOB '*[^a-zA-Z0-9_]*')),
        due_at REAL,
        launching_at REAL,
        sent_at REAL,
        finished_at REAL,
        CHECK (words IS NULL OR (capability = 'reset_message' AND state IN ('counting', 'ready', 'held')
                                 AND typeof(words) = 'text' AND length(words) BETWEEN 1 AND 8192)),
        CHECK ((capability = 'reset_message') = (record_id IS NOT NULL)),
        CHECK (ordinal > 0 OR capability = 'reset_credit')
    );

CREATE INDEX reset_rules_state ON reset_rules(state);

CREATE TABLE credit_spends (
        spend_id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id INTEGER NOT NULL,
        bucket TEXT NOT NULL CHECK (bucket IN ('codex', 'premium', 'legacy', 'other')),
        minutes INTEGER NOT NULL CHECK (typeof(minutes) = 'integer' AND minutes >= 1 AND minutes <= 100800),
        occasion INTEGER NOT NULL CHECK (typeof(occasion) = 'integer' AND occasion >= 0),
        attempt_id TEXT NOT NULL CHECK (length(attempt_id) = 36 AND attempt_id NOT GLOB '*[^0-9a-f-]*'),
        created_at REAL NOT NULL,
        tries INTEGER NOT NULL CHECK (typeof(tries) = 'integer' AND tries >= 1 AND tries <= 2),
        outcome TEXT CHECK (outcome IS NULL OR outcome IN ('reset', 'nothing_to_reset', 'no_credit', 'already_redeemed', 'unknown')),
        finished_at REAL,
        UNIQUE (bucket, minutes, occasion)
    );

CREATE INDEX credit_spends_created ON credit_spends(created_at);

ALTER TABLE records ADD COLUMN queue_id TEXT CHECK (queue_id IS NULL OR (length(queue_id) = 36 AND queue_id NOT GLOB '*[^0-9a-f-]*'));

ALTER TABLE records ADD COLUMN withdraw INTEGER NOT NULL DEFAULT 0 CHECK (withdraw IN (0, 1));

CREATE TABLE continuations (
        answer_id TEXT PRIMARY KEY CHECK (answer_id IS NULL OR (length(answer_id) = 64 AND answer_id NOT GLOB '*[^0-9a-f]*')),
        capability TEXT NOT NULL CHECK (capability IN ('empty_response', 'subagent_parent', 'keep_going', 'usage_wrap_up', 'usage_pause')),
        kind TEXT NOT NULL CHECK (kind IN ('empty_response', 'subagent', 'keep_going', 'wrap_up', 'after_reset')),
        thread_id TEXT NOT NULL CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*'),
        record_id TEXT CHECK (record_id IS NULL OR (length(record_id) = 64 AND record_id NOT GLOB '*[^0-9a-f]*')),
        ordinal INTEGER CHECK (ordinal IS NULL OR (typeof(ordinal) = 'integer' AND ordinal >= 0)),
        words TEXT CHECK (words IS NULL OR (typeof(words) = 'text' AND length(words) BETWEEN 1 AND 2000)),
        chain INTEGER NOT NULL CHECK (typeof(chain) = 'integer' AND chain >= 0),
        created_at REAL NOT NULL,
        finished_at REAL,
        reason TEXT CHECK (reason IS NULL OR reason IN ('sent', 'delivered', 'unknown', 'superseded', 'handed_over', 'withdrawn', 'chain_spent', 'goal_left', 'mentioned', 'turned_off', 'conversation_off')),
        launching_at REAL,
        CHECK (words IS NULL OR finished_at IS NULL)
    );

CREATE INDEX continuations_thread ON continuations(thread_id);

CREATE TABLE keep_going (
        thread_id TEXT PRIMARY KEY CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*'),
        count INTEGER NOT NULL CHECK (typeof(count) = 'integer' AND count >= 1 AND count <= 10),
        used INTEGER NOT NULL CHECK (typeof(used) = 'integer' AND used >= 0),
        armed_at REAL NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('on', 'done')),
        reason TEXT CHECK (reason IS NULL OR reason IN ('no_progress', 'plan_done', 'count_spent', 'goal_active', 'failed', 'plan_unreadable', 'by_person', 'turned_off', 'conversation_off')),
        finished_at REAL,
        CHECK (used <= count)
    );

CREATE TABLE prompts (
        prompt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*'),
        words TEXT,
        trigger TEXT NOT NULL CHECK (trigger IN ('after_turn', 'at_time', 'recurring')),
        at REAL,
        every TEXT CHECK (every IS NULL OR every IN ('day', 'week')),
        occurrences INTEGER NOT NULL CHECK (typeof(occurrences) = 'integer' AND occurrences >= 1 AND occurrences <= 30),
        sent_count INTEGER NOT NULL CHECK (typeof(sent_count) = 'integer' AND sent_count >= 0),
        until REAL,
        depends INTEGER NOT NULL CHECK (depends IN (0, 1)),
        position INTEGER NOT NULL CHECK (typeof(position) = 'integer' AND position >= 0),
        state TEXT NOT NULL CHECK (state IN ('waiting', 'ready', 'held', 'done', 'cancelled')),
        reason TEXT CHECK (reason IS NULL OR reason IN ('delivered', 'handed_over', 'superseded', 'expired', 'missed', 'dependency_failed', 'by_person', 'turned_off', 'too_long', 'conversation_off', 'withdrawn', 'withdraw_refused', 'unknown', 'turn_running')),
        record_id TEXT CHECK (record_id IS NULL OR (length(record_id) = 64 AND record_id NOT GLOB '*[^0-9a-f]*')),
        gate TEXT CHECK (gate IS NULL OR (length(gate) BETWEEN 1 AND 48 AND gate NOT GLOB '*[^a-zA-Z0-9_]*')),
        gate_reason TEXT CHECK (gate_reason IS NULL OR (length(gate_reason) BETWEEN 1 AND 48 AND gate_reason NOT GLOB '*[^a-zA-Z0-9_]*')),
        created_at REAL NOT NULL,
        due_at REAL,
        launching_at REAL,
        sent_at REAL,
        finished_at REAL,
        CHECK (words IS NULL OR (state IN ('waiting', 'ready', 'held') AND typeof(words) = 'text'
                                 AND length(words) BETWEEN 1 AND 8192)),
        CHECK (occurrences = 1 OR trigger = 'recurring'),
        CHECK ((every IS NULL) = (trigger <> 'recurring')),
        CHECK (until IS NULL OR until - created_at <= 2592000),
        CHECK (sent_count <= occurrences)
    );

CREATE INDEX prompts_thread ON prompts(thread_id, position);

CREATE TABLE meter (
        bucket TEXT NOT NULL CHECK (bucket IN ('codex', 'premium', 'legacy', 'other')),
        minutes INTEGER NOT NULL CHECK (typeof(minutes) = 'integer' AND minutes >= 1 AND minutes <= 100800),
        used_percent REAL NOT NULL CHECK (typeof(used_percent) IN ('real', 'integer') AND used_percent >= 0),
        reset_at INTEGER CHECK (reset_at IS NULL OR (typeof(reset_at) = 'integer' AND reset_at >= 0)),
        read_at REAL NOT NULL,
        warned_reset_at INTEGER CHECK (warned_reset_at IS NULL OR (typeof(warned_reset_at) = 'integer' AND warned_reset_at >= 0)),
        warned_at REAL,
        paused_reset_at INTEGER CHECK (paused_reset_at IS NULL OR (typeof(paused_reset_at) = 'integer' AND paused_reset_at >= 0)),
        PRIMARY KEY (bucket, minutes)
    );

CREATE TABLE wordings (
        capability TEXT NOT NULL,
        choice TEXT NOT NULL,
        words TEXT NOT NULL CHECK (typeof(words) = 'text' AND length(words) BETWEEN 1 AND 2000),
        changed_at REAL NOT NULL,
        PRIMARY KEY (capability, choice)
    );

CREATE TABLE headless_runs (
        interruption_id TEXT PRIMARY KEY CHECK (length(interruption_id) = 64 AND interruption_id NOT GLOB '*[^0-9a-f]*'),
        capability TEXT NOT NULL CHECK (capability IN ('headless_run', 'compact_continue', 'model_fallback')),
        thread_id TEXT NOT NULL CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*'),
        started_at REAL NOT NULL,
        ends_by REAL NOT NULL,
        stop_requested_at REAL,
        ended_at REAL,
        end TEXT CHECK (end IS NULL OR end IN ('completed', 'failed', 'interrupted', 'capped', 'yielded', 'lost', 'refused_settings')),
        restore_model TEXT CHECK (restore_model IS NULL OR (typeof(restore_model) = 'text'
                                  AND length(restore_model) BETWEEN 1 AND 128 AND capability = 'model_fallback')),
        CHECK ((end IS NULL) = (ended_at IS NULL))
    );

CREATE TABLE chat_messages (
        chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*'),
        words TEXT CHECK (words IS NULL OR (typeof(words) = 'text' AND length(words) BETWEEN 1 AND 2000)),
        state TEXT NOT NULL CHECK (state IN ('waiting', 'in_flight', 'done', 'cancelled')),
        reason TEXT CHECK (reason IS NULL OR reason IN ('delivered', 'not_taken', 'withdrawn', 'cancelled', 'turned_off', 'conversation_off', 'unknown')),
        record_id TEXT NOT NULL UNIQUE CHECK (length(record_id) = 64 AND record_id NOT GLOB '*[^0-9a-f]*'),
        created_at REAL NOT NULL,
        sent_at REAL,
        finished_at REAL,
        CHECK (words IS NULL OR state = 'waiting')
    );

CREATE INDEX chat_messages_thread ON chat_messages(thread_id, chat_id);

ALTER TABLE prompts ADD COLUMN while_running TEXT NOT NULL DEFAULT 'queue' CHECK (while_running IN ('queue', 'wait'));

CREATE TABLE usage_samples (
        bucket TEXT NOT NULL CHECK (bucket IN ('codex', 'premium', 'legacy', 'other')),
        minutes INTEGER NOT NULL CHECK (typeof(minutes) = 'integer' AND minutes >= 1 AND minutes <= 100800),
        at REAL NOT NULL,
        used_percent REAL NOT NULL CHECK (typeof(used_percent) IN ('real', 'integer') AND used_percent >= 0),
        reset_at INTEGER CHECK (reset_at IS NULL OR (typeof(reset_at) = 'integer' AND reset_at >= 0)),
        PRIMARY KEY (bucket, minutes, at)
    );

CREATE INDEX usage_samples_at ON usage_samples(at);

CREATE TABLE token_days (
        day TEXT NOT NULL CHECK (length(day) = 10 AND day GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'),
        thread_id TEXT NOT NULL CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*'),
        project_digest TEXT CHECK (project_digest IS NULL OR (length(project_digest) = 16 AND project_digest NOT GLOB '*[^0-9a-f]*')),
        input INTEGER NOT NULL CHECK (typeof(input) = 'integer' AND input >= 0),
        cached INTEGER NOT NULL CHECK (typeof(cached) = 'integer' AND cached >= 0),
        output INTEGER NOT NULL CHECK (typeof(output) = 'integer' AND output >= 0),
        reasoning INTEGER NOT NULL CHECK (typeof(reasoning) = 'integer' AND reasoning >= 0),
        turns INTEGER NOT NULL CHECK (typeof(turns) = 'integer' AND turns >= 0),
        PRIMARY KEY (day, thread_id)
    );

CREATE TABLE token_files (
        file_digest TEXT PRIMARY KEY CHECK (length(file_digest) = 16 AND file_digest NOT GLOB '*[^0-9a-f]*'),
        thread_id TEXT NOT NULL CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*'),
        size INTEGER NOT NULL CHECK (typeof(size) = 'integer' AND size >= 0),
        offset INTEGER NOT NULL CHECK (typeof(offset) = 'integer' AND offset >= 0),
        mtime_ns INTEGER NOT NULL CHECK (typeof(mtime_ns) = 'integer' AND mtime_ns >= 0),
        read_at REAL NOT NULL
    );

CREATE TABLE outbox (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT NOT NULL CHECK (channel IN ('ntfy', 'webhook', 'telegram', 'email')),
        event TEXT NOT NULL CHECK (event IN ('usage_limit_detected', 'recovered', 'failed', 'needs_you', 'stopped_unexpectedly', 'restarted', 'update_offered', 'test')),
        category TEXT CHECK (category IS NULL OR category IN ('auth_service_transient', 'network_transient', 'rate_limit_transient', 'server_5xx', 'stream_interrupted', 'terminal_auth', 'terminal_failure', 'terminal_invalid', 'terminal_permission', 'terminal_policy', 'terminal_user', 'timeout', 'unknown', 'usage_limit')),
        alias TEXT CHECK (alias IS NULL OR (length(alias) BETWEEN 6 AND 9 AND alias GLOB 'task [1-9]*' AND substr(alias, 6) NOT GLOB '*[^0-9]*')),
        at REAL NOT NULL,
        tries INTEGER NOT NULL CHECK (typeof(tries) = 'integer' AND tries >= 0 AND tries <= 3),
        state TEXT NOT NULL CHECK (state IN ('waiting', 'sent', 'dropped')),
        finished_at REAL,
        CHECK ((state = 'waiting') = (finished_at IS NULL))
    );

CREATE INDEX outbox_at ON outbox(at);

CREATE TABLE feed (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        checked_at REAL,
        word TEXT CHECK (word IS NULL OR word IN ('operational', 'degraded', 'outage', 'unknown')),
        codex_word TEXT CHECK (codex_word IS NULL OR codex_word IN ('operational', 'degraded', 'outage', 'unknown')),
        incidents INTEGER CHECK (incidents IS NULL OR (typeof(incidents) = 'integer' AND incidents >= 0 AND incidents <= 99))
    );

CREATE TABLE remote (
        channel TEXT PRIMARY KEY CHECK (channel IN ('telegram')),
        paired_at REAL,
        bad_codes INTEGER NOT NULL DEFAULT 0 CHECK (typeof(bad_codes) = 'integer' AND bad_codes >= 0 AND bad_codes <= 5),
        update_offset INTEGER CHECK (update_offset IS NULL OR (typeof(update_offset) = 'integer' AND update_offset >= 0)),
        code_digest TEXT CHECK (code_digest IS NULL OR (length(code_digest) = 64
                                AND code_digest NOT GLOB '*[^0-9a-f]*')),
        code_expires_at REAL,
        CHECK (code_digest IS NULL OR paired_at IS NULL)
    );

CREATE TABLE opens (
        open_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*'),
        record_id TEXT NOT NULL CHECK (length(record_id) = 64 AND record_id NOT GLOB '*[^0-9a-f]*'),
        at REAL NOT NULL,
        outcome TEXT NOT NULL CHECK (outcome IN ('opened', 'loaded', 'not_loaded', 'refused'))
    );

CREATE INDEX opens_at ON opens(at);

CREATE TABLE restarts (
        at REAL PRIMARY KEY,
        exit_code INTEGER CHECK (exit_code IS NULL OR typeof(exit_code) = 'integer'),
        restarted INTEGER NOT NULL CHECK (restarted IN (0, 1))
    );

CREATE TABLE account_seen (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        identity_digest TEXT CHECK (identity_digest IS NULL OR (length(identity_digest) = 16 AND identity_digest NOT GLOB '*[^0-9a-f]*')),
        plan TEXT CHECK (plan IS NULL OR plan IN ('free', 'plus', 'pro', 'team', 'business', 'enterprise', 'edu', 'other')),
        read_at REAL NOT NULL
    );

CREATE TABLE hook_claims (
        interruption_id TEXT PRIMARY KEY CHECK (length(interruption_id) = 64 AND interruption_id NOT GLOB '*[^0-9a-f]*'),
        turn_digest TEXT NOT NULL CHECK (length(turn_digest) = 64 AND turn_digest NOT GLOB '*[^0-9a-f]*'),
        at REAL NOT NULL,
        outcome TEXT NOT NULL CHECK (outcome IN ('blocked', 'passed', 'refused'))
    );

CREATE INDEX hook_claims_at ON hook_claims(at);

CREATE TABLE steers (
        steer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL CHECK (length(thread_id) = 36 AND thread_id NOT GLOB '*[^0-9a-f-]*'),
        words TEXT NOT NULL CHECK (length(words) BETWEEN 1 AND 8192),
        client_id TEXT NOT NULL CHECK (length(client_id) = 36 AND client_id NOT GLOB '*[^0-9a-f-]*'),
        state TEXT NOT NULL CHECK (state IN ('requested', 'sending', 'accepted', 'unconfirmed', 'refused')),
        reason TEXT CHECK (reason IS NULL OR reason IN ('no_turn', 'not_held', 'no_pipe', 'app_refused', 'held', 'expired', 'conversation_off', 'turned_off')),
        created_at REAL NOT NULL,
        finished_at REAL,
        CHECK ((state IN ('requested', 'sending')) = (finished_at IS NULL)),
        CHECK ((state = 'refused') = (reason IS NOT NULL))
    );

CREATE INDEX steers_created ON steers(created_at);

PRAGMA application_id=1128333319;

PRAGMA user_version=9;

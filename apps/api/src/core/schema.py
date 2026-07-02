SCHEMA_DDL: str = """
CREATE TABLE IF NOT EXISTS characters (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  profile_json TEXT NOT NULL,
  source_format TEXT NOT NULL DEFAULT 'json',
  source_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_profiles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  profile_json TEXT NOT NULL,
  source_format TEXT NOT NULL DEFAULT 'json',
  source_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plots (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  character_id TEXT NOT NULL,
  user_profile_id TEXT NOT NULL,
  plot_json TEXT NOT NULL,
  source_format TEXT NOT NULL DEFAULT 'json',
  source_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(character_id) REFERENCES characters(id),
  FOREIGN KEY(user_profile_id) REFERENCES user_profiles(id)
);
CREATE TABLE IF NOT EXISTS preference_profiles (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  scope_id TEXT,
  profile_json TEXT NOT NULL,
  source_format TEXT NOT NULL DEFAULT 'json',
  source_text TEXT,
  confidence REAL NOT NULL DEFAULT 1.0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  plot_id TEXT NOT NULL,
  title TEXT,
  active_adapter_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(plot_id) REFERENCES plots(id)
);
CREATE TABLE IF NOT EXISTS conversation_settings (
  conversation_id TEXT PRIMARY KEY,
  provider TEXT,
  model TEXT,
  num_predict INTEGER,
  num_ctx INTEGER,
  compact_prompt INTEGER,
  adapter_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  turn_id TEXT,
  generation_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
CREATE TABLE IF NOT EXISTS turns (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  user_message_id TEXT NOT NULL,
  selected_generation_id TEXT,
  regenerate_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(conversation_id) REFERENCES conversations(id),
  FOREIGN KEY(user_message_id) REFERENCES messages(id)
);
CREATE TABLE IF NOT EXISTS generations (
  id TEXT PRIMARY KEY,
  turn_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  plot_id TEXT NOT NULL,
  character_id TEXT NOT NULL,
  user_profile_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  adapter_id TEXT,
  candidate_index INTEGER NOT NULL,
  prompt_snapshot TEXT NOT NULL,
  prompt_hash TEXT NOT NULL,
  output_text TEXT NOT NULL,
  params_json TEXT NOT NULL,
  output_token_count INTEGER,
  selected INTEGER NOT NULL DEFAULT 0,
  rejected INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(turn_id) REFERENCES turns(id),
  FOREIGN KEY(conversation_id) REFERENCES conversations(id),
  FOREIGN KEY(plot_id) REFERENCES plots(id),
  FOREIGN KEY(character_id) REFERENCES characters(id),
  FOREIGN KEY(user_profile_id) REFERENCES user_profiles(id)
);
CREATE TABLE IF NOT EXISTS user_actions (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  turn_id TEXT,
  generation_id TEXT,
  action_type TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
CREATE TABLE IF NOT EXISTS generation_edits (
  id TEXT PRIMARY KEY,
  generation_id TEXT NOT NULL,
  original_text TEXT NOT NULL,
  edited_text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(generation_id) REFERENCES generations(id)
);
"""

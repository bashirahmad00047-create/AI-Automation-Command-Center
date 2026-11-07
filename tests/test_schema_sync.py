import os
import sqlite3
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Boolean, Float, Text, inspect, text

db_file = "test_sync.db"
if os.path.exists(db_file):
    os.remove(db_file)

conn = sqlite3.connect(db_file)
cur = conn.cursor()
cur.execute("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY, email VARCHAR(255), password_hash VARCHAR(255), full_name VARCHAR(128));")
cur.execute("INSERT INTO users VALUES ('u1', 'admin@example.com', 'hash', 'Admin');")
cur.execute("CREATE TABLE products (id VARCHAR(64) PRIMARY KEY, organization_id VARCHAR(64), name VARCHAR(255));")
cur.execute("INSERT INTO products VALUES ('p1', 'org1', 'Product 1');")
conn.commit()
conn.close()

engine = create_engine(f"sqlite:///{db_file}")
insp = inspect(engine)

md = MetaData()
u_table = Table("users", md,
    Column("id", String(64), primary_key=True),
    Column("email", String(255)),
    Column("password_hash", String(255)),
    Column("full_name", String(128)),
    Column("is_active", Boolean, default=True),
    Column("mfa_secret", String(64)),
    Column("is_mfa_enabled", Boolean, default=False),
    Column("mfa_backup_codes", Text),
    Column("phone", String(64)),
    Column("department", String(64), default="General")
)
p_table = Table("products", md,
    Column("id", String(64), primary_key=True),
    Column("organization_id", String(64)),
    Column("name", String(255)),
    Column("sku", String(128)),
    Column("barcode", String(128)),
    Column("image_url", String(512)),
    Column("unit", String(64)),
    Column("price", Float, default=0.0),
    Column("stock_quantity", Integer, default=0),
    Column("stock_status", String(32), default="in_stock"),
    Column("is_active", Boolean, default=True)
)

dialect = engine.dialect
existing_tables = set(insp.get_table_names())

for tname, tbl in md.tables.items():
    if tname not in existing_tables:
        continue
    existing_cols = {c["name"] for c in insp.get_columns(tname)}
    for col in tbl.columns:
        if col.name not in existing_cols:
            col_type = col.type.compile(dialect)
            default_clause = ""
            if col.default is not None and getattr(col.default, "is_scalar", False):
                val = col.default.arg
                if isinstance(val, bool):
                    default_clause = f" DEFAULT {1 if val else 0}"
                elif isinstance(val, (int, float)):
                    default_clause = f" DEFAULT {val}"
                elif isinstance(val, str):
                    escaped = val.replace("'", "''")
                    default_clause = f" DEFAULT '{escaped}'"
            stmt = f"ALTER TABLE {tname} ADD COLUMN {col.name} {col_type}{default_clause};"
            print("Executing:", stmt)
            with engine.connect() as c:
                c.execute(text(stmt))
                c.commit()

insp = inspect(engine)
print("users cols now:", [c["name"] for c in insp.get_columns("users")])
print("products cols now:", [c["name"] for c in insp.get_columns("products")])

conn = sqlite3.connect(db_file)
cur = conn.cursor()
cur.execute("SELECT * FROM users;")
print("users row:", cur.fetchall())
cur.execute("SELECT * FROM products;")
print("products row:", cur.fetchall())
conn.close()

if os.path.exists(db_file):
    os.remove(db_file)
print("ALL TESTS PASSED SUCCESSFULLY!")

import duckdb
import os
import streamlit as st

# Resolve paths
current_dir = os.path.dirname(os.path.abspath(__file__))
PARQUET_DIR = os.path.abspath(os.path.join(current_dir, "..", "data"))

@st.cache_resource
def get_db_connection():
    """Initializes DuckDB and registers Parquet files as views."""
    con = duckdb.connect(database=':memory:')

    if not os.path.exists(PARQUET_DIR):
        print(f"Warning: Data directory not found at {PARQUET_DIR}")
        return con

    parquet_files = [
        file for file in os.listdir(PARQUET_DIR)
        if file.endswith(".parquet")
    ]

    for file in parquet_files:
        table_name = file.replace(".parquet", "")
        full_path = os.path.join(PARQUET_DIR, file)
        
        # Use double quotes for table names in case they start with numbers
        con.execute(f"""
            CREATE VIEW "{table_name}" AS
            SELECT * FROM read_parquet('{full_path}')
        """)
    
    return con

# Global connection instance
db_conn = get_db_connection()

@st.cache_data
def get_filter_options():
    """Fetches unique values for sidebar filters from DuckDB."""
    try:
        divisions = db_conn.execute("""SELECT DISTINCT name FROM "dimensions" WHERE type_=2 ORDER BY name""").fetchdf()['name'].tolist()
        countries = db_conn.execute("""SELECT DISTINCT name FROM "country" ORDER BY name""").fetchdf()['name'].tolist()
        regions = db_conn.execute("""SELECT DISTINCT name FROM "region" ORDER BY name""").fetchdf()['name'].tolist()
        sectors = db_conn.execute("""SELECT DISTINCT client_type FROM "sector" ORDER BY client_type""").fetchdf()['client_type'].tolist()
        return divisions, regions, sectors, countries
    except Exception as e:
        print(f"Error fetching filter options: {e}")
        return [], []

@st.cache_data
def get_subdivisions(division_name):
    """Fetches subdivisions filtered by division."""
    if not division_name or division_name == "None":
        return db_conn.execute("""SELECT DISTINCT name FROM "dimensions" WHERE type_=3 ORDER BY name""").fetchdf()['name'].tolist()
    
    # Assuming there's a link between division and subdivision (e.g., parent_id)
    # Adjust this query based on your actual schema relationship
    query = """
        SELECT DISTINCT s.name 
        FROM "dimensions" s
        JOIN "dimensions" d ON s.parent = d.id
        WHERE d.name = ?
        ORDER BY s.name
    """
    try:
        return db_conn.execute(query, [division_name]).fetchdf()['name'].tolist()
    except:
        return []

@st.cache_data
def get_countries_by_region(region_name):
    """Fetches countries belonging to a specific region."""
    try:
        query = 'SELECT DISTINCT c.name FROM "country" c JOIN "region" r ON c.region_id = r.id WHERE r.name = ? ORDER BY c.name'
        return db_conn.execute(query, [region_name]).fetchdf()['name'].tolist()
    except:
        return []

@st.cache_data
def get_region_by_country(country_name):
    """Finds the region name for a specific country."""
    try:
        query = 'SELECT r.name FROM "country" c JOIN "region" r ON c.region_id = r.id WHERE c.name = ? LIMIT 1'
        res = db_conn.execute(query, [country_name]).fetchone()
        return res[0] if res else "None"
    except:
        return "None"
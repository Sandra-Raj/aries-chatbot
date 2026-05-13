from db import db_conn
import streamlit as st

def get_client_enquiries(enq_type=None, enq_status=None):
    """
    Returns client enquiries based on sidebar filters AND AI-driven parameters.
    
    Args:
        enq_type (str): Optional filter for 'Project', 'Annual Contract', etc.
        enq_status (str): Optional filter for 'Open', 'Cancel', 'Lost', etc.
    """
    filters = st.session_state.get("active_filters", {})
    
    # We use a CTE (WITH base_data AS ...) so we can filter by the calculated 
    # text labels (enquiry_type, enquiry_status) instead of raw IDs.
    query = """
    WITH base_data AS (
        SELECT 
            e.book_no,
            e.enquiry_date,
            dc.name AS company,
            dv.name AS division,
            ds.name AS subdivision,
            CASE 
                WHEN CAST(NULLIF(CAST(e.debtor_no AS VARCHAR), '') AS BIGINT) != 0 
                     AND CAST(NULLIF(CAST(e.branch_code AS VARCHAR), '') AS BIGINT) != 0 
                THEN d.name
                WHEN e.enquiry_temp_id != 0 THEN t.client_name
                ELSE 'Unknown'
            END AS client,
            cn.name AS country,
            r.name AS region,
            ct.client_type AS sector,
            CASE e.enq_type
                WHEN 1 THEN 'Project'
                WHEN 2 THEN 'Annual Contract'
                WHEN 3 THEN 'Shutdown'
                WHEN 4 THEN 'Callout'
                WHEN 5 THEN 'Tender'
                ELSE 'Other'
            END AS enquiry_type,
            CASE e.enq_status
                WHEN 0 THEN 'Open'
                WHEN 1 THEN 'Cancel'
                WHEN 2 THEN 'Lost'
                WHEN 3 THEN 'Transfer'
                WHEN 4 THEN 'Confirmed'
                WHEN 5 THEN 'BID Enquiry'
                ELSE 'Other'
            END AS enquiry_status,
            (e.aprox_amount * e.rate) as amount_aed
        FROM "client_enquiry" e
        LEFT JOIN "dimensions" dc ON e.company = dc.id
        LEFT JOIN "dimensions" dv ON e.division = dv.id
        LEFT JOIN "dimensions" ds ON e.subdivision = ds.id
        LEFT JOIN "debtors_master" d ON e.debtor_no = d.debtor_no
        LEFT JOIN "temp_clients" t ON e.enquiry_temp_id = t.temp_clients_id
        LEFT JOIN "country" cn ON cn.id = (
            CASE 
                WHEN CAST(NULLIF(CAST(e.debtor_no AS VARCHAR), '') AS BIGINT) != 0 
                     AND CAST(NULLIF(CAST(e.branch_code AS VARCHAR), '') AS BIGINT) != 0 
                THEN CAST(NULLIF(CAST(d.country AS VARCHAR), '') AS BIGINT)
                ELSE CAST(NULLIF(CAST(t.country AS VARCHAR), '') AS BIGINT)
            END
        )
        LEFT JOIN "region" r ON cn.region_id = r.id
        LEFT JOIN "client_type" ct ON e.client_type = ct.id
        WHERE e.parent_id = 0 
          AND e.is_active = 1 
          AND e.enq_status <= 5
          AND NOT (e.branch_code = 0 AND e.enquiry_temp_id = 0 AND e.debtor_no = 0)
    )
    SELECT * FROM base_data
    WHERE 1=1
    """

    params = []

    if filters.get("division"):
        query += " AND division = ?"
        params.append(filters["division"])
    
    if filters.get("subdivision"):
        query += " AND subdivision = ?"
        params.append(filters["subdivision"])
        
    if filters.get("country"):
        query += " AND country = ?"
        params.append(filters["country"])

    if filters.get("region"):
        query += " AND region = ?"
        params.append(filters["region"])

    if filters.get("sector"):
        query += " AND sector = ?"
        params.append(filters["sector"])

    if filters.get("start_date") and filters.get("end_date"):
        query += " AND enquiry_date BETWEEN ? AND ?"
        params.append(filters["start_date"])
        params.append(filters["end_date"])

    # Filter by Enquiry Type (e.g., 'Project', 'Shutdown')
    if enq_type and enq_type != "None":
        query += " AND enquiry_type = ?"
        params.append(enq_type)

    # Filter by Enquiry Status (e.g., 'Open', 'Confirmed')
    if enq_status and enq_status != "None":
        query += " AND enquiry_status = ?"
        params.append(enq_status)

    query += " ORDER BY enquiry_date DESC"

    return db_conn.execute(query, params).fetchdf()

def get_top_clients(division: str, limit: int = 10):
    """Get top clients by profit/revenue for a division."""
    query = """
    SELECT
        m.name AS client_name,
        SUM((t.ov_amount * t.rate) - t.total_expense_aed) AS total_profit
    FROM "debtor_trans" t
    JOIN "debtors_master" m ON t.debtor_no = m.debtor_no
    JOIN "dimensions" d ON t.dimension2_id = d.id
    WHERE d.name = ?
    GROUP BY t.debtor_no, m.name
    ORDER BY total_profit DESC
    LIMIT ?
    """
    return db_conn.execute(query, [division, limit]).fetchdf()

def get_inactive_clients(division: str):
    """Get inactive clients for a division based on last enquiry."""
    query = """
    SELECT
        m.name AS client_name,
        la.last_job_date,
        la.last_enquiry_date
    FROM (
        SELECT
            debtor_no,
            division,
            MAX(job_date) AS last_job_date,
            MAX(enquiry_date) AS last_enquiry_date
        FROM "client_activity_status"
        GROUP BY debtor_no, division
    ) la
    JOIN "debtors_master" m ON la.debtor_no = m.debtor_no
    JOIN "dimensions" d ON la.division = d.id
    WHERE d.name = ?
    """
    return db_conn.execute(query, [division]).fetchdf()

def get_total_revenue():
    """Calculate total company revenue from allocations."""
    query = """
    SELECT
        SUM(a.alloc_amount * a.bank_rate) AS total_revenue
    FROM "cust_allocations" a
    JOIN "debtor_trans" t ON a.trans_no_to = t.trans_no
    WHERE a.trans_type_from = 12
    """
    return db_conn.execute(query).fetchdf()

# Mapping for the Router
FUNCTION_MAP = {
    "get_top_clients": get_top_clients,
    "get_inactive_clients": get_inactive_clients,
    "get_total_revenue": get_total_revenue,
    "get_client_enquiries": get_client_enquiries
}
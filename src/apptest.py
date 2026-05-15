#app.py
import os
import re
import json
import streamlit as st
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from thefuzz import process, fuzz
from datetime import datetime, timedelta

# Absolute imports
try:
    from tools import FUNCTION_MAP
    from db import fuzzy_find_division, fuzzy_find_subdivision, get_filter_options, get_subdivisions, get_countries_by_region, get_region_by_country
except ImportError:
    from src.tools import FUNCTION_MAP
    from src.db import fuzzy_find_division, fuzzy_find_subdivision, get_filter_options, get_subdivisions, get_countries_by_region, get_region_by_country

load_dotenv()

# Define Intent Clusters (The "Meaning" of each function)
INTENT_CLUSTERS = {
    "get_client_enquiries": [
        "enquiry", "enquiries", "job", "jobs", "job enquiry", "client leads",
        "show me enquiries", "list all jobs", "status of jobs",
        # Status-based phrases
        "open", "cancelled", "lost", "transfer", "confirmed", "bid enquiry",
        "open enquiries", "lost jobs", "confirmed orders",
        # Type-based phrases
        "project", "annual contract", "shutdown", "callout", "tender",
        "shutdown enquiries", "tender jobs", "callout enquiry", "annual jobs"
    ]
}

# =========================================================
# CONFIG & LLM
# =========================================================
AI_MODEL = os.getenv("AI_MODEL", "phi3:latest")
COMPANY_API_LINK = os.getenv("COMPANY_API_LINK")

# Optimized LLM setup for speed
llm = ChatOllama(
    model=AI_MODEL,
    base_url=COMPANY_API_LINK,
    temperature=0,
    num_predict=256, 
    stop=["Question:", "User Question:", "\n\n", "```"]
)

# =========================================================
# SIDEBAR FILTERS
# =========================================================
st.sidebar.title("📊 Data Filters")
st.sidebar.markdown("Filter the chatbot's scope:")

div_list, region_list, sector_list, country_list = get_filter_options()

# Division & Dependent Subdivision
sel_division = st.sidebar.selectbox(
    "Division", 
    ["None"] + div_list, 
    key="sidebar_division")

sub_div_list = get_subdivisions(sel_division)
sel_subdivision = st.sidebar.selectbox(
    "Subdivision", 
    ["None"] + sub_div_list,
    key="sidebar_subdivision"
)

# Region & Country (Mutual Dependency)
# We use keys and session state to handle the bidirectional link
if "region_sync" not in st.session_state:
    st.session_state.region_sync = "None"
if "country_sync" not in st.session_state:
    st.session_state.country_sync = "None"

def on_region_change():
    st.session_state.country_sync = "None"

def on_country_change():
    if st.session_state.country_sync != "None":
        st.session_state.region_sync = get_region_by_country(st.session_state.country_sync)
    else:
        st.session_state.region_sync = "None"

# Region Dropdown
sel_region = st.sidebar.selectbox(
    "Region", 
    ["None"] + region_list, 
    key="region_sync", 
    on_change=on_region_change
)

# Filter country list based on region
if sel_region != "None":
    country_list = get_countries_by_region(sel_region)
else:
    # If no region, show all countries
    div_list, region_list, sector_list, country_list = get_filter_options()

sel_country = st.sidebar.selectbox(
    "Country", 
    ["None"] + country_list, 
    key="country_sync", 
    on_change=on_country_change
)

# Sector Filter
sel_sector = st.sidebar.selectbox("Sector", ["None"] + sector_list) 

# Date Range Filters
st.sidebar.markdown("---")
st.sidebar.subheader("Date Range")
start_date = st.sidebar.date_input("Start Date", value=None)
end_date = st.sidebar.date_input("End Date", value=None)

if st.sidebar.button("Clear All Filters"):
    st.rerun()

if "last_tool_call" not in st.session_state:
    st.session_state.last_tool_call = None

# Bundle filters into a session state or dictionary for the tools to use later
st.session_state.active_filters = {
    "division": sel_division if sel_division != "None" else None,
    "subdivision": sel_subdivision if sel_subdivision != "None" else None,
    "region": sel_region if sel_region != "None" else None,
    "country": sel_country if sel_country != "None" else None,
    "start_date": start_date,
    "end_date": end_date
}

def vector_router(query):
    query = query.lower()
    
    # --- INTENT CLASSIFICATION (Meaning) ---
    all_intents = []
    intent_labels = []
    
    for label, phrases in INTENT_CLUSTERS.items():
        all_intents.extend(phrases)
        intent_labels.extend([label] * len(phrases))

    # Vectorize phrases + user query
    vectorizer = TfidfVectorizer().fit_transform(all_intents + [query])
    vectors = vectorizer.toarray()
    
    # Compare query (last vector) against all intents
    # cosine_similarity returns a score between 0 and 1
    similarities = cosine_similarity([vectors[-1]], vectors[:-1])[0]
    best_match_idx = similarities.argmax()
    
    # Set a threshold (e.g., 0.3) to avoid false positives
    if similarities[best_match_idx] > 0.3:
        intent = intent_labels[best_match_idx]
    else:
        intent = "get_client_enquiries" # Default fallback

    # --- ENTITY EXTRACTION (Fuzzy Matching) ---
    # We use fuzzy matching to fix typos in Statuses or Divisions
    extracted_args = {}
    
    # --- 1. DIVISION EXTRACTION ---
    matched_div = fuzzy_find_division(query)
    if matched_div:
        # Update the hidden filter
        st.session_state.active_filters["division"] = matched_div
        # Sync the Sidebar UI
        st.session_state.sidebar_division = matched_div
        
        # --- 2. SUBDIVISION EXTRACTION (Only if Division is found) ---
        matched_sub = fuzzy_find_subdivision(query, matched_div)
        if matched_sub:
            st.session_state.active_filters["subdivision"] = matched_sub
            st.session_state.sidebar_subdivision = matched_sub

    if intent == "get_client_enquiries":
        # Fuzzy match the status
        status_options = ["Open", "Cancel", "Lost", "Transfer", "Confirmed", "BID Enquiry"]
        # Find best match in the query string
        match, score = process.extractOne(query, status_options, scorer=fuzz.token_set_ratio)
        if score > 70: # Confidence threshold
            extracted_args["enq_status"] = match
        # Fuzzy match the type
        type_options = ["Project", "Annual Contract", "Shutdown", "Callout", "Tender"]
        # Find best match in the query string
        match, score = process.extractOne(query, type_options, scorer=fuzz.token_set_ratio)
        if score > 70: # Confidence threshold
            extracted_args["enq_type"] = match
    
    # --- 3. DATE EXTRACTION (New Logic) ---
    start_date = None
    today = datetime.today() # Default end date is today
    match = re.search(r'(this|past|last)\s+(?:(\d+)\s+)?(day|week|month|year)s?', query)

    if match:
        count = int(match.group(2)) if match.group(2) else 1
        unit = match.group(3)
        if 'day' in unit:
            start_date = today - timedelta(days=count)
        elif 'week' in unit:
            start_date = today - timedelta(weeks=count)
        elif 'month' in unit:
            start_date = today - timedelta(days=count * 30) # Approximation
        elif 'year' in unit:
            start_date = today - timedelta(days=count * 365) # Approximation


    # If we found a date, add it to arguments
    if start_date:
        # This keeps Division, Country, etc. and only changes the dates
        st.session_state.active_filters.update({
            "start_date": start_date, 
            "end_date": today
        })
            
    return {"function": intent, "arguments": extracted_args}

def generate_final_response(user_query, dataframe):
    template = """
    You are a professional BI Assistant. Answer the question based ONLY on the provided data.
    
    STRICT RULES:
    - BE PRECISE. Use as few words as possible.
    - ALL financial figures are in AED.
    - AVOID jargon like "As a BI analyst".
    - If the user asked for a specific status (e.g. 'Open'), mention only those rows.
    - DO NOT explain the process.
    - If it's a single value, just state it.
    
    User Question: {question}
    Data: {result}
    
    Answer:"""
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({
        "question": user_query, 
        "result": dataframe.to_string(index=False)
    })
# =========================================================
# UI LAYOUT
# =========================================================
st.set_page_config(page_title="Aries BI", page_icon="🤖")
st.title("Aries Marine BI Assistant")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = [AIMessage(content="How can I help you with Aries Marine data today?")]

# Display History
for message in st.session_state.chat_history:
    role = "assistant" if isinstance(message, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(message.content)
        if hasattr(message, "data") and message.data is not None:
            if not (message.data.shape == (1, 1)):
                st.dataframe(message.data)

# Input
user_query = st.chat_input("Ask a question...")

if user_query:
    # Add human message and rerun to show it immediately
    st.session_state.chat_history.append(HumanMessage(content=user_query))
    st.rerun()

# Processing (Triggered after rerun if the last message is from a Human)
if len(st.session_state.chat_history) > 0 and isinstance(st.session_state.chat_history[-1], HumanMessage):
    last_query = st.session_state.chat_history[-1].content
    
    with st.chat_message("assistant"):
        # STEP 1: ROUTE (Instant, no LLM used here)
        tool_data = vector_router(last_query)
        st.session_state.last_tool_call = tool_data
        res_df = None
        
        if tool_data.get("function") in FUNCTION_MAP:
            # STEP 2: FETCH DATA (Spinner for DB only)
            with st.spinner("Fetching data..."):
                func = FUNCTION_MAP[tool_data["function"]]
                res_df = func(**tool_data.get("arguments", {}))
            
            if res_df is not None and not res_df.empty:
                # Fix Serial Numbers and Display Table Immediately
                is_single = (res_df.shape == (1, 1))
                if not is_single:
                    res_df.index = range(1, len(res_df) + 1)
                    st.dataframe(res_df)
                    answer = "Here is the data you requested:"                    
                else:
                    # STEP 3: Generate text summary (Secondary spinner, ONLY LLM CALL)
                    with st.spinner("Summarizing results..."):
                        answer = generate_final_response(last_query, res_df)
                        st.markdown(answer)
            else:
                answer = "No records found matching your filters."
                st.markdown(answer)
        else:
            answer = "I'm not sure which function to use. Try being more specific."
            st.markdown(answer)

        # Store in history with data attached
        new_ai_msg = AIMessage(content=answer)
        new_ai_msg.data = res_df
        st.session_state.chat_history.append(new_ai_msg)
        
        # Final rerun to clear spinner and lock the view
        st.rerun()
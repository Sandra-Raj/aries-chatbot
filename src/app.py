import os
import re
import json
import streamlit as st
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage

# Absolute imports
try:
    from tools import FUNCTION_MAP
    from db import get_filter_options, get_subdivisions, get_countries_by_region, get_region_by_country
except ImportError:
    from src.tools import FUNCTION_MAP
    from src.db import get_filter_options, get_subdivisions, get_countries_by_region, get_region_by_country

load_dotenv()

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
sel_division = st.sidebar.selectbox("Division", ["None"] + div_list)

sub_div_list = get_subdivisions(sel_division)
sel_subdivision = st.sidebar.selectbox("Subdivision", ["None"] + sub_div_list)

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

# Bundle filters into a session state or dictionary for the tools to use later
st.session_state.active_filters = {
    "division": sel_division if sel_division != "None" else None,
    "subdivision": sel_subdivision if sel_subdivision != "None" else None,
    "region": sel_region if sel_region != "None" else None,
    "country": sel_country if sel_country != "None" else None,
    "start_date": start_date,
    "end_date": end_date
}

# =========================================================
# ROUTING LOGIC (Context Aware)
# =========================================================
INTENT_TEMPLATE = """You are a technical router for Aries Marine. Based on history and question, output a JSON object to call the correct function.

Chat history: {history}

FUNCTIONS:
1. get_client_enquiries(enq_type, enq_status) - Use for ANY question about enquiries, status or type.
    - enq_type: 'Project', 'Annual Contract', 'Shutdown', 'Callout', 'Tender', or 'None'
    - enq_status: 'Open', 'Cancel', 'Lost', 'Transfer', 'Confirmed', 'BID Enquiry', or 'None'
2. get_total_revenue() - Use for company revenue. DO NOT PASS ARGUMENTS.
3. get_top_clients(division: string, limit: integer)
4. get_inactive_clients(division: string)

IMPORTANT:
- Output ONLY valid JSON.
- For get_total_revenue, the "arguments" field MUST be {{}}.
- NEVER add extra keys like "type", or "status_open" to the arguments.

For example:

User Question: "give all open client enquiries under division I&M in the last 3 months"
Response:
    {{
        "function": "get_client_enquiries",
        "arguments": {{
            "enq_status": "Open"
        }}
    }}
User Question: {question}
Response:
"""

# =========================================================
# UTILITIES
# =========================================================
def choose_function(user_query, chat_history):
    history_str = "\n".join([f"{m.type}: {m.content}" for m in chat_history[-3:]])
    
    prompt = ChatPromptTemplate.from_template(INTENT_TEMPLATE)
    chain = prompt | llm | StrOutputParser()
    
    response = chain.invoke({"question": user_query, "history": history_str})
    print(f"DEBUG - Raw AI: {response}")

    try:
        # Step 1: If the model repeated the prompt examples, isolate the text after "Response:"
        target_text = response
        if "Response:" in response:
            target_text = response.split("Response:")[-1]

        # Step 2: Use greedy matching (.* instead of .*?) to capture the FULL JSON block.
        # This ensures that internal braces like in "arguments": {} do not truncate the string.
        match = re.search(r'(\{.*\})', target_text, re.DOTALL)
        
        if not match:
            return {"function": None, "arguments": {}}
        
        json_str = match.group(1)
        
        # Step 3: Clean potential comments or markdown leftovers
        json_str = re.sub(r'//.*', '', json_str)
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        
        # Step 4: Fix potential trailing commas before closing braces/brackets
        json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
        
        parsed = json.loads(json_str)
        
        # Safety check for required keys
        if "function" not in parsed:
            return {"function": None, "arguments": {}}
        if "arguments" not in parsed:
            parsed["arguments"] = {}
        return parsed
            
    except Exception as e:
        print(f"Router Error during parsing: {e}")
    return {"function": None, "arguments": {}}


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
        # STEP 1: Route immediately (Hidden spinner)
        tool_data = choose_function(last_query, st.session_state.chat_history[:-1])
        res_df = None

        if tool_data.get("function") in FUNCTION_MAP:
            # STEP 2: Fetch Data
            with st.spinner("Fetching from database..."):
                func = FUNCTION_MAP[tool_data["function"]]
                res_df = func(**tool_data.get("arguments", {}))
            
            if res_df is not None and not res_df.empty:
                is_single = (res_df.shape == (1, 1))
                print(res_df.shape)
                if not is_single:
                    res_df.index = range(1, len(res_df) + 1)
                    st.dataframe(res_df)
                    print(res_df)
                    
                    # STEP 3: Generate text summary (Secondary spinner)
                    with st.spinner("Summarizing results..."):
                        answer = generate_final_response(last_query, res_df)
                        st.markdown(answer)
                else:
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
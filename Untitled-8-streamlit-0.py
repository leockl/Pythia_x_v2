import streamlit as st
import openai
import psycopg2
import matplotlib.pyplot as plt
import io
import base64
from psycopg2.extras import RealDictCursor
import datetime
import numpy as np  # Add this import to handle NaN (Not a Number) values
import matplotlib.dates as mdates  # Add this import for handling dates in Matplotlib

# Replace with your OpenAI API key
openai.api_key = 'empty'

# Database connection parameters
db_params = {
    'dbname': 'postgres',
    'user': 'viewer_account',
    'password': 'empty',
    'host': '136.144.62.142',
    'port': '5432'
}

SCHEMA = '''
CREATE TABLE trades (
exchange character varying(20),
symbol character varying(20),
price double precision,
size double precision,
taker_side character varying(5),
trade_id character varying(64),
event_timestamp timestamp without time zone,
atom_timestamp bigint
);

CREATE TABLE trades_l3 (
    exchange character varying(20),
    symbol character varying(20),
    price double precision,
    size double precision,
    taker_side character varying(5),
    trade_id character varying(64),
    maker_order_id character varying(64),
    taker_order_id character varying(64),
    event_timestamp timestamp without time zone,
    atom_timestamp bigint
);

CREATE TABLE candle (
    exchange character varying(20),
    symbol character varying(20),
    start timestamp without time zone,
    "end" timestamp without time zone,
    "interval" character varying(10),
    trades integer,
    closed boolean,
    o double precision,
    h double precision,
    l double precision,
    c double precision,
    v double precision,
    event_timestamp timestamp without time zone,
    atom_timestamp bigint
);

CREATE TABLE ethereum_blocks (
    blocktimestamp timestamp without time zone,
    atomtimestamp bigint,
    number integer,
    hash character(66) NOT NULL,
    parenthash character(66),
    nonce character(18),
    sha3uncles character(66),
    logsbloom character(514),
    transactionsroot character(66),
    stateroot character(66),
    receiptsroot character(66),
    miner character(42),
    difficulty bigint,
    totaldifficulty numeric,
    extradata text,
    size bigint,
    gaslimit numeric,
    gasused numeric
);

CREATE TABLE ethereum_logs (
    atomtimestamp bigint,
    blocktimestamp timestamp without time zone NOT NULL,
    logindex integer NOT NULL,
    transactionindex integer,
    transactionhash character(66) NOT NULL,
    blockhash character(66),
    blocknumber bigint,
    address character(42),
    data text,
    topic0 text,
    topic1 text,
    topic2 text,
    topic3 text
)

CREATE TABLE ethereum_transactions (
    blocktimestamp timestamp without time zone NOT NULL,
    atomtimestamp bigint,
    blocknumber integer,
    blockhash character(66),
    hash character(66) NOT NULL,
    nonce text,
    transactionindex integer,
    fromaddr character(42),
    toaddr character(42),
    value numeric,
    gas bigint,
    gasprice bigint,
    input text,
    maxfeepergas bigint,
    maxpriorityfeepergas bigint,
    type text
)

CREATE TABLE ethereum_token_transfers (
    atomtimestamp bigint,
    blocktimestamp timestamp without time zone NOT NULL,
    tokenaddr character(42),
    fromaddr text,
    toaddr text,
    value numeric,
    transactionhash character(66) NOT NULL,
    logindex integer NOT NULL,
    blocknumber bigint,
    blockhash character(66)
)
'''

def execute_query(query):
    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(query)
        result = cursor.fetchall()
        conn.commit()
        return result
    except Exception as e:
        st.error(f"Database error: {e}")
        return None
    finally:
        cursor.close()
        conn.close()

def rearrange_columns_for_datetime(data):
    """
    Rearranges the columns in each row of the data so that the first column is
    one that contains a date or time, if present.
    """
    if not data:
        return data

    date_or_time_keys = [key for key in data[0].keys() if "date" in key.lower() or "time" in key.lower()]
    if not date_or_time_keys:
        return data  # Return the data as-is if there are no date/time columns

    # Move the date or time column to the first position
    for i, row in enumerate(data):
        ordered_row = {key: row[key] for key in date_or_time_keys + [k for k in row.keys() if k not in date_or_time_keys]}
        data[i] = ordered_row

    return data

def find_group_column(data):
    """
    Dynamically identifies a potential column for grouping data based on the criterion
    of having a moderate number of unique values and being categorical (non-numeric),
    considering any variable names that contain 'time' or 'date'.
    """
    # This function assumes 'data' is a list of dictionaries where each dictionary represents a row.
    if not data:
        return None, False

    # Extract first row to determine column data types
    first_row = data[0]

    # Define a helper function to check if a value is numeric
    def is_numeric(value):
        try:
            float(value)
            return True
        except ValueError:
            return False

    # Identify non-numeric (categorical) columns excluding 'time' or 'date'
    potential_group_columns = [col for col in first_row.keys() if not is_numeric(first_row[col]) and 'time' not in col and 'date' not in col]

    # Iterate over potential group columns to find a suitable grouping column
    for col in potential_group_columns:
        unique_values = {item[col] for item in data}
        if 1 < len(unique_values) <= 10:  # Adjust this range as needed
            return col, True

    return None, False

def is_numeric(value):
    """
    Determines if a value is numeric. Now also correctly handles datetime objects
    and any variable names that contain 'time' or 'date', explicitly excluding them
    from being considered numeric.
    """
    if isinstance(value, (datetime.datetime, datetime.date)):
        return False  # Correctly handle datetime objects by excluding them
    try:
        float(value)
        return True
    except (ValueError, TypeError):  # Catch TypeError to handle any unexpected non-numeric types
        return False

def determine_chart_type(data):
    """
    Enhanced to determine the most appropriate chart type based on data types,
    including dynamic grouping for multi-line charts, considering any variable names
    that contain 'time' or 'date'.
    """
    if not data:
        return ['text'], None  # New case for empty data

    first_row = data[0]
    numeric_columns = [col for col, val in first_row.items() if is_numeric(val)]
    categorical_columns = [col for col in first_row.keys() if col not in numeric_columns and 'time' not in col and 'date' not in col]

    if any('time' in col or 'date' in col for col in first_row):
        group_column, is_suitable_for_multi_line = find_group_column(data)
        if is_suitable_for_multi_line:
            return ['multi-line'], group_column
        else:
            return ['line'], None
    elif len(numeric_columns) > 1:
        return ['scatter'], None
    elif len(categorical_columns) >= 1 and len(numeric_columns) == 1:
        return ['bar', 'pie'], None
    else:
        return ['text'], None  # Fallback for unexpected data shapes

def generate_charts(data, chart_types, group_column=None):
    charts = {}
    if not data:
        return charts  # Early return if there's no data or chart type is text

    # Convert all dates to strings for Matplotlib compatibility
    for i, item in enumerate(data):
        for key, value in item.items():
            if isinstance(value, datetime.datetime):
                data[i][key] = value.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(value, datetime.date):
                data[i][key] = value.strftime('%Y-%m-%d')
            # Additional conversion not required here, keeping the logic focused on dates

    for chart_type in chart_types:
        plt.figure()
        all_keys = list(data[0].keys())
        
        # Identify the first column that contains date or time information for the x-axis
        x_column_name = next((col for col in all_keys if "date" in col.lower() or "time" in col.lower()), None)
        x_values = []
        
        if x_column_name:  # If a date/time column is found, prepare x_values accordingly
            for item in data:
                if '-' in item[x_column_name]:  # Assuming the presence of '-' indicates a date
                    x_values.append(datetime.datetime.strptime(item[x_column_name], '%Y-%m-%d').date())
                else:
                    x_values.append(item[x_column_name])  # Non-date values
            # Convert dates to Matplotlib's internal date format
            x_values = mdates.date2num(x_values)
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.gcf().autofmt_xdate()
        else:  # Use the first column or group column if no date/time column is found
            x_column_name = group_column if group_column else all_keys[0]
            x_values = [item[x_column_name] for item in data]

        y_column_names = [key for key in all_keys if key != x_column_name]

        for y_column_name in y_column_names:
            y_values = [item[y_column_name] for item in data]

            if chart_type == 'multi-line' and group_column and y_column_name != group_column:
                # Plot logic for multi-line charts
                plt.figure()
                grouped_data = {}
                for i, item in enumerate(data):
                    group_value = item[group_column]
                    if group_value not in grouped_data:
                        grouped_data[group_value] = []
                    grouped_data[group_value].append((x_values[i], y_values[i]))

                for group, vals in grouped_data.items():
                    xs, ys = zip(*vals)
                    plt.plot(xs, ys, label=group)
                plt.legend()
            elif chart_type == 'line':
                plt.plot(x_values, y_values)
            elif chart_type == 'scatter':
                plt.scatter(x_values, y_values)
            elif chart_type == 'bar':
                plt.bar(x_values, y_values)
            elif chart_type == 'pie' and all(isinstance(i, (int, float)) for i in y_values) and sum(y_values) > 0:
                plt.pie(y_values, labels=x_values, autopct='%1.1f%%')
                plt.axis('equal')

            plt.xlabel(x_column_name if x_column_name else 'X-axis')
            plt.ylabel(y_column_name)

        st.pyplot(plt)
        plt.close()

    return charts

def decode_base64_image(base64_string):
    """Decode a base64 string into bytes suitable for streamlit.image."""
    return io.BytesIO(base64.b64decode(base64_string))

def generate_summary(data):
    """Generates a summary for given data using OpenAI's API."""
    prompt = "Summarize this data in natural language: " + str(data)
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Adjust according to the latest available model
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        summary = response.choices[0].message['content']
        return summary
    except Exception as e:
        st.error(f"Error generating summary: {e}")
        return "Error generating summary."
    
# Streamlit UI
st.title('Pythia X')

user_question = st.text_input('Enter your question:', '')

if user_question:
    try:
        # Include conversation history in the request to OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Adjust according to the latest available model
            messages=[
                {"role": "system", "content": f"""You are a program which translates natural language into read-only SQL commands. \
                                               Use the following table schema: {SCHEMA}. You only output SQL queries. Your \
                                               queries are designed to be used as timeseries charts from Apache Superset. \
                                               Trading pairs are in the form "<base>.<quote>", where <base> and <quote> are \
                                               uppercase. Exchanges "binance" and "coinbase" use the trades_l3 table for their \
                                               trades, all other exchanges use the trades table. All exchange names are \
                                               lowercase. Input:"""},
                {"role": "user", "content": f"Translate this natural language question to SQL: \"{user_question}\""}
            ],
            temperature=0.7
        )
        sql_query = response.choices[0].message['content'].strip()
        
        # Trim Markdown code block syntax accurately and ensure "sql" prefix is properly removed
        if sql_query.startswith("```sql"):
            sql_query = sql_query[6:]  # Remove starting "```sql"
        elif sql_query.startswith("sql"):
            sql_query = sql_query[3:]  # Remove starting "sql" if it's directly at the beginning
        
        sql_query = sql_query.strip(" `\n")  # Trim spaces, backticks, and newlines from both ends

        # Code to output the generated SQL query
        st.write("Generated SQL Query:")
        st.code(sql_query, language="sql")

    except Exception as e:
        st.error(f"Failed to generate SQL query: {e}")
        sql_query = None

    # Execute the SQL query
    if sql_query:
        query_result = execute_query(sql_query)
        if query_result:
            st.success('Query executed successfully.')

            # Rearrange columns so that date/time columns are first
            query_result = rearrange_columns_for_datetime(query_result)

            # Check if user requested a chart
            chart_requested = "chart" in user_question.lower()
            if chart_requested:
                chart_types, group_column = determine_chart_type(query_result)
                charts = generate_charts(query_result, chart_types, group_column)
                # for chart_type, chart_base64 in charts.items():
                #     decoded_image = decode_base64_image(chart_base64)
                #     st.image(decoded_image, caption=f"{chart_type.capitalize()} Chart", use_column_width=True)
            else:
                # Display results as a table if chart is not requested
                st.write("Query Results:")
                st.table(query_result)
        
            # Directly generate and display a summary of the query result
            summary = generate_summary(query_result)
            st.write(summary)

        else:
            st.error("Failed to execute SQL query or no results to display.")
    else:
        st.error("No SQL query generated to execute.")

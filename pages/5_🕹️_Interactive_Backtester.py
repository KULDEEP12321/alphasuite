import streamlit as st
from datetime import datetime
import traceback
import os

# Import the necessary functions from your backtesting engine
from quant_engine import (
    run_pybroker_full_backtest,
    plot_performance_vs_benchmark,
    plot_trades_on_chart
)
from load_cfg import WORKING_DIRECTORY

st.set_page_config(page_title="Interactive Backtester", layout="wide")

st.title("🕹️ Interactive Strategy Backtester")

st.markdown("""
This tool allows you to run a backtest on a single ticker using a pre-trained model and visualize its performance.

**Important:** This is an **in-sample** backtest. It's useful for visualizing how a saved model behaves over different time periods, but it is **not** a substitute for the out-of-sample results from the `train` command.

**Prerequisite:** You must first train a model for the ticker and strategy you wish to test using the `train` command (e.g., `python quant_engine.py train --ticker SPY --strategy-type uptrend_pullback`).
""")

# --- Session State Initialization ---
if 'bt_artifacts' not in st.session_state:
    st.session_state.bt_artifacts = None

# --- UI Controls ---
st.subheader("Backtest Configuration")

def clear_bt_results():
    """Callback to clear backtest results when the selection changes."""
    if 'bt_artifacts' in st.session_state:
        st.session_state.bt_artifacts = None

def get_available_trained_models():
    """Scans the models directory and returns a list of available ticker/strategy combinations."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models_dir = os.path.join(project_root, 'pybroker_trainer', 'artifacts')
    if not os.path.exists(models_dir):
        return []

    available_models = []
    for f in os.listdir(models_dir):
        # The `_results.pkl` file is the one artifact guaranteed to exist for any trained strategy (ML or non-ML).
        # We use this file to discover all available backtest results.
        if f.endswith('_results.pkl'):
            # Example filename: SPY_ma_crossover_results.pkl
            parts = f.replace('_results.pkl', '').split('_')
            if len(parts) >= 2:
                ticker = parts[0]
                strategy = "_".join(parts[1:])
                available_models.append(f"{ticker} - {strategy}")
    return sorted(available_models)

available_models = get_available_trained_models()

col1, col2 = st.columns([2, 1])

with col1:
    selected_model = st.selectbox(
        "Select a Trained Model (Ticker & Strategy):",
        options=available_models,
        help="This list is populated from trained models found in the `pybroker_trainer/artifacts/` directory.",
        key="selected_model_bt",
        on_change=clear_bt_results
    )

with col2:
    cash_input = st.number_input(
        "Starting cash ($):",
        min_value=1000.0,
        value=100000.0,
        step=10000.0,
        format="%.0f",
        key="cash_bt",
        on_change=clear_bt_results,
    )

col3, col4, col5, col6 = st.columns([1, 1, 1, 2])
_MIN_DATE = datetime(1980, 1, 1)
_MAX_DATE = datetime.now()
with col3:
    start_date_input = st.date_input(
        "Start Date",
        value=datetime(2015, 1, 1),
        min_value=_MIN_DATE,
        max_value=_MAX_DATE,
        key="start_date_bt",
        on_change=clear_bt_results,
    )

with col4:
    end_date_input = st.date_input(
        "End Date",
        value=_MAX_DATE,
        min_value=_MIN_DATE,
        max_value=_MAX_DATE,
        key="end_date_bt",
        on_change=clear_bt_results,
    )

with col5:
    commission_input = st.number_input(
        "Commission (per share):",
        min_value=0.0,
        value=0.005,
        step=0.001,
        format="%.4f",
        key="commission_bt",
        on_change=clear_bt_results,
    )

with col6:
    st.write("") # Spacer
    st.write("") # Spacer
    run_button = st.button("🚀 Run Backtest", use_container_width=True, disabled=not available_models)

# --- Main Logic ---
if run_button:
    if not selected_model:
        st.warning("No trained models available to run a backtest.")
        st.session_state.bt_artifacts = None
    else:
        ticker_input, strategy_select = selected_model.split(' - ', 1)

        with st.spinner(f"Running backtest for {ticker_input} with {strategy_select} strategy..."):
            try:
                backtest_artifacts = run_pybroker_full_backtest(
                    ticker=ticker_input,
                    strategy_type=strategy_select,
                    start_date=start_date_input.strftime('%Y-%m-%d'),
                    end_date=end_date_input.strftime('%Y-%m-%d'),
                    commission_cost=commission_input,
                    initial_cash=float(cash_input),
                )
                st.session_state.bt_artifacts = backtest_artifacts
                st.session_state.bt_ticker = ticker_input # Save for display
                st.session_state.bt_strategy = strategy_select # Save for display
                if backtest_artifacts is None:
                    st.error(f"Backtest failed. This usually means a model for '{ticker_input}' with strategy '{strategy_select}' has not been trained yet. Please run the `train` command first.")
            except Exception as e:
                st.error(f"An unexpected error occurred during the backtest: {e}")
                st.code(traceback.format_exc())
                st.session_state.bt_artifacts = None

# --- Display Results ---
if st.session_state.bt_artifacts:
    result = st.session_state.bt_artifacts['result']
    ticker = st.session_state.get('bt_ticker', 'N/A')
    strategy = st.session_state.get('bt_strategy', 'N/A')

    st.markdown("---")
    st.header(f"Backtest Results for {ticker} ({strategy})")

    tab1, tab2, tab3 = st.tabs(["📊 Summary Metrics", "📈 Equity Curve", "📉 Trade Chart"])

    with tab1:
        # --- Convert metrics DataFrame to be Arrow-compatible ---
        # The metrics_df from pybroker can have mixed types in its 'value' column
        # (e.g., numbers and datetimes), which causes pyarrow serialization errors.
        # We convert the entire DataFrame to strings for robust display.
        metrics_display_df = result.metrics_df.astype(str)
        st.dataframe(metrics_display_df, use_container_width=True)

    with tab2:
        # --- Use a standard if/else block to prevent printing the DeltaGenerator object ---
        fig_equity = plot_performance_vs_benchmark(result, f"Equity Curve for {ticker} ({strategy})")
        if fig_equity:
            st.pyplot(fig_equity)
        else:
            st.warning("Could not generate equity curve plot.")

    with tab3:
        # --- Use a standard if/else block to prevent printing the DeltaGenerator object ---
        fig_trades = plot_trades_on_chart(result, ticker, f"Trades for {ticker} ({strategy})")
        if fig_trades:
            st.pyplot(fig_trades)
        else:
            st.warning("Could not generate trade chart.")
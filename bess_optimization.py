import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import linprog
from datetime import datetime, timedelta
import warnings
import os
warnings.filterwarnings('ignore')

# ============================================================================
# ASSET PARAMETERS
# ============================================================================
POWER_MW = 100          # Max charge/discharge rate (MW)
ENERGY_MWH = 200        # Battery capacity (MWh)
EFFICIENCY = 0.85       # Round-trip efficiency (applied on charge)
INITIAL_SOC = 0.0       # Initial state of charge (MWh)
MAX_DAILY_THROUGHPUT = 200  # Maximum discharge per day (MWh) - 1 full cycle

# ============================================================================
# DATA INGESTION & CLEANING
# ============================================================================
def load_and_clean_data(filepath):
    """
    Load CSV data and handle irregularities.
    
    Parameters:
    -----------
    filepath : str
        Path to the CSV file
        
    Returns:
    --------
    pd.DataFrame
        Cleaned dataframe with datetime index
    """
    print("=" * 70)
    print("LOADING AND CLEANING DATA")
    print("=" * 70)
    
    # Load CSV
    df = pd.read_csv(filepath)
    print(f"✓ Loaded {len(df)} records from CSV")
    
    # Parse datetime
    df['SETTLEMENTDATE'] = pd.to_datetime(df['SETTLEMENTDATE'], format='%d/%m/%Y %H:%M')
    df = df.sort_values('SETTLEMENTDATE').reset_index(drop=True)
    
    # Extract date for daily grouping
    df['DATE'] = df['SETTLEMENTDATE'].dt.date
    
    # Check for missing intervals
    expected_interval = timedelta(minutes=5)
    time_diffs = df['SETTLEMENTDATE'].diff()
    missing_intervals = time_diffs[time_diffs > expected_interval]
    
    if len(missing_intervals) > 0:
        print(f"⚠ Warning: Found {len(missing_intervals)} gaps in time series")
        for idx in missing_intervals.index:
            print(f"  Gap at {df.loc[idx, 'SETTLEMENTDATE']}")
    else:
        print("✓ No missing intervals detected")
    
    # Check for duplicates
    duplicates = df.duplicated(subset=['SETTLEMENTDATE'])
    if duplicates.any():
        print(f"⚠ Warning: Found {duplicates.sum()} duplicate timestamps")
        df = df.drop_duplicates(subset=['SETTLEMENTDATE'], keep='first')
    else:
        print("✓ No duplicate timestamps")
    
    # Check for negative or extreme prices
    print(f"✓ Price range: ${df['RRP'].min():.2f} to ${df['RRP'].max():.2f}")
    
    # Summary statistics
    unique_days = df['DATE'].nunique()
    print(f"✓ Total days in dataset: {unique_days}")
    print(f"✓ Records per day: {len(df) / unique_days:.0f} (expected: 288)")
    
    return df


# ============================================================================
# LINEAR PROGRAMMING OPTIMIZATION
# ============================================================================
def optimize_daily_dispatch(prices, dt_hours=1/12):
    """
    Optimize battery dispatch for a single day using Linear Programming.
    
    Decision Variables:
    - charge[t]: Energy charged in interval t (MWh)
    - discharge[t]: Energy discharged in interval t (MWh)
    - soc[t]: State of charge at end of interval t (MWh)
    
    Objective:
    - Maximize: sum(discharge[t] * price[t] - charge[t] * price[t])
    
    Constraints:
    1. Power limits: 0 <= charge[t], discharge[t] <= POWER_MW * dt_hours
    2. SOC limits: 0 <= soc[t] <= ENERGY_MWH
    3. SOC dynamics: soc[t] = soc[t-1] + charge[t] * EFFICIENCY - discharge[t]
    4. Initial/Final SOC: soc[0] = 0, soc[T] = 0
    5. Throughput limit: sum(discharge[t]) <= MAX_DAILY_THROUGHPUT
    
    Parameters:
    -----------
    prices : array-like
        Array of prices for each time interval ($/MWh)
    dt_hours : float
        Time interval in hours (default: 1/12 for 5-minute intervals)
        
    Returns:
    --------
    dict
        Dictionary containing charge, discharge, soc arrays and revenue
    """
    n = len(prices)
    prices = np.array(prices)
    
    # For LP, we need to convert to minimization problem
    # Original: maximize sum(discharge[t] * price[t] - charge[t] * price[t])
    # Convert: minimize sum(-discharge[t] * price[t] + charge[t] * price[t])
    
    # Decision variables: [charge[0], ..., charge[n-1], discharge[0], ..., discharge[n-1], soc[0], ..., soc[n-1]]
    n_vars = 3 * n
    
    # Objective function coefficients
    c = np.zeros(n_vars)
    c[0:n] = prices           # charge variables (minimize cost)
    c[n:2*n] = -prices        # discharge variables (maximize revenue)
    # soc variables don't appear in objective
    
    # Inequality constraints (A_ub @ x <= b_ub)
    A_ub = []
    b_ub = []
    
    # Power limit constraints
    max_energy = POWER_MW * dt_hours  # Max energy per interval
    
    # charge[t] <= max_energy for all t
    for t in range(n):
        constraint = np.zeros(n_vars)
        constraint[t] = 1
        A_ub.append(constraint)
        b_ub.append(max_energy)
    
    # discharge[t] <= max_energy for all t
    for t in range(n):
        constraint = np.zeros(n_vars)
        constraint[n + t] = 1
        A_ub.append(constraint)
        b_ub.append(max_energy)
    
    # SOC constraints: soc[t] <= ENERGY_MWH for all t
    for t in range(n):
        constraint = np.zeros(n_vars)
        constraint[2*n + t] = 1
        A_ub.append(constraint)
        b_ub.append(ENERGY_MWH)
    
    # Throughput constraint: sum(discharge[t]) <= MAX_DAILY_THROUGHPUT
    throughput_constraint = np.zeros(n_vars)
    throughput_constraint[n:2*n] = 1
    A_ub.append(throughput_constraint)
    b_ub.append(MAX_DAILY_THROUGHPUT)
    
    A_ub = np.array(A_ub)
    b_ub = np.array(b_ub)
    
    # Equality constraints (A_eq @ x = b_eq)
    A_eq = []
    b_eq = []
    
    # SOC dynamics: soc[t] = soc[t-1] + charge[t] * EFFICIENCY - discharge[t]
    # Rearranged: charge[t] * EFFICIENCY - discharge[t] - soc[t] + soc[t-1] = 0
    
    # Initial condition: soc[0] = charge[0] * EFFICIENCY - discharge[0]
    constraint = np.zeros(n_vars)
    constraint[0] = EFFICIENCY      # charge[0]
    constraint[n] = -1              # discharge[0]
    constraint[2*n] = -1            # soc[0]
    A_eq.append(constraint)
    b_eq.append(0)
    
    # For t = 1 to n-1: soc[t] = soc[t-1] + charge[t] * EFFICIENCY - discharge[t]
    for t in range(1, n):
        constraint = np.zeros(n_vars)
        constraint[t] = EFFICIENCY          # charge[t]
        constraint[n + t] = -1              # discharge[t]
        constraint[2*n + t] = -1            # soc[t]
        constraint[2*n + t - 1] = 1         # soc[t-1]
        A_eq.append(constraint)
        b_eq.append(0)
    
    # Final condition: soc[n-1] = 0
    constraint = np.zeros(n_vars)
    constraint[2*n + n - 1] = 1
    A_eq.append(constraint)
    b_eq.append(0)
    
    A_eq = np.array(A_eq)
    b_eq = np.array(b_eq)
    
    # Bounds: all variables >= 0
    bounds = [(0, None) for _ in range(n_vars)]
    
    # Solve LP
    result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, 
                     bounds=bounds, method='highs')
    
    if not result.success:
        raise ValueError(f"Optimization failed: {result.message}")
    
    # Extract solution
    charge = result.x[0:n]
    discharge = result.x[n:2*n]
    soc = result.x[2*n:3*n]
    
    # Calculate revenue (negative of minimized cost)
    revenue = -result.fun
    
    # Calculate actual throughput
    throughput = np.sum(discharge)
    
    return {
        'charge': charge,
        'discharge': discharge,
        'soc': soc,
        'revenue': revenue,
        'throughput': throughput,
        'success': result.success
    }


# ============================================================================
# MAIN OPTIMIZATION LOOP
# ============================================================================
def run_optimization(df):
    """
    Run optimization for all days in the dataset.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Cleaned dataframe with price data
        
    Returns:
    --------
    pd.DataFrame
        Dataframe with optimization results for all intervals
    """
    print("\n" + "=" * 70)
    print("RUNNING DAILY OPTIMIZATION")
    print("=" * 70)
    
    results_list = []
    total_revenue = 0
    
    # Group by date and optimize each day
    for date, day_df in df.groupby('DATE'):
        print(f"\nOptimizing {date}...")
        
        # Extract prices
        prices = day_df['RRP'].values
        n_intervals = len(prices)
        
        print(f"  • Intervals: {n_intervals}")
        print(f"  • Price range: ${prices.min():.2f} to ${prices.max():.2f}")
        
        # Optimize
        result = optimize_daily_dispatch(prices, dt_hours=5/60)
        
        print(f"  • Revenue: ${result['revenue']:,.2f}")
        print(f"  • Throughput: {result['throughput']:.2f} MWh (limit: {MAX_DAILY_THROUGHPUT} MWh)")
        print(f"  • Max SOC: {result['soc'].max():.2f} MWh")
        
        # Store results
        day_results = day_df.copy()
        day_results['charge_mw'] = result['charge'] / (5/60)  # Convert MWh to MW
        day_results['discharge_mw'] = result['discharge'] / (5/60)  # Convert MWh to MW
        day_results['charge_mwh'] = result['charge']
        day_results['discharge_mwh'] = result['discharge']
        day_results['soc_mwh'] = result['soc']
        day_results['revenue'] = result['discharge'] * prices - result['charge'] * prices
        
        results_list.append(day_results)
        total_revenue += result['revenue']
    
    # Combine all results
    results_df = pd.concat(results_list, ignore_index=True)
    
    print("\n" + "=" * 70)
    print("OPTIMIZATION SUMMARY")
    print("=" * 70)
    print(f"Total Revenue: ${total_revenue:,.2f}")
    print(f"Average Daily Revenue: ${total_revenue / df['DATE'].nunique():,.2f}")
    print("=" * 70)
    
    return results_df, total_revenue


# ============================================================================
# VISUALIZATION
# ============================================================================
def create_visualization(results_df, total_revenue, script_dir):
    """
    Create visualization of price vs battery state of charge.
    
    Parameters:
    -----------
    results_df : pd.DataFrame
        Dataframe with optimization results
    total_revenue : float
        Total revenue across all days
    script_dir : str
        Directory where script is located
    """
    print("\nCreating visualization...")
    
    fig, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True)
    
    # Prepare data
    x = results_df['SETTLEMENTDATE']
    prices = results_df['RRP']
    soc = results_df['soc_mwh']
    charge = results_df['charge_mw']
    discharge = results_df['discharge_mw']
    
    # Plot 1: Price
    axes[0].plot(x, prices, color='#2E86AB', linewidth=1.5, label='Dispatch Price')
    axes[0].set_ylabel('Price ($/MWh)', fontsize=11, fontweight='bold')
    axes[0].set_title('BESS Dispatch Optimization - South Australia (SA1)', 
                     fontsize=14, fontweight='bold', pad=15)
    axes[0].grid(True, alpha=0.3, linestyle='--')
    axes[0].legend(loc='upper right')
    
    # Add daily separation lines
    for date in results_df['DATE'].unique()[1:]:
        date_start = pd.Timestamp(date)
        for ax in axes:
            ax.axvline(date_start, color='red', linestyle='--', alpha=0.5, linewidth=1)
    
    # Plot 2: State of Charge
    axes[1].fill_between(x, 0, soc, color='#A23B72', alpha=0.6, label='State of Charge')
    axes[1].plot(x, soc, color='#A23B72', linewidth=1.5)
    axes[1].axhline(ENERGY_MWH, color='red', linestyle='--', alpha=0.5, 
                    label=f'Capacity ({ENERGY_MWH} MWh)')
    axes[1].set_ylabel('SOC (MWh)', fontsize=11, fontweight='bold')
    axes[1].set_ylim(-5, ENERGY_MWH + 10)
    axes[1].grid(True, alpha=0.3, linestyle='--')
    axes[1].legend(loc='upper right')
    
    # Plot 3: Charging Activity
    axes[2].fill_between(x, 0, charge, color='#F18F01', alpha=0.6, label='Charging')
    axes[2].plot(x, charge, color='#F18F01', linewidth=1.5)
    axes[2].axhline(POWER_MW, color='red', linestyle='--', alpha=0.5, 
                    label=f'Max Power ({POWER_MW} MW)')
    axes[2].set_ylabel('Charge (MW)', fontsize=11, fontweight='bold')
    axes[2].set_ylim(-5, POWER_MW + 5)
    axes[2].grid(True, alpha=0.3, linestyle='--')
    axes[2].legend(loc='upper right')
    
    # Plot 4: Discharging Activity
    axes[3].fill_between(x, 0, discharge, color='#06A77D', alpha=0.6, label='Discharging')
    axes[3].plot(x, discharge, color='#06A77D', linewidth=1.5)
    axes[3].axhline(POWER_MW, color='red', linestyle='--', alpha=0.5, 
                    label=f'Max Power ({POWER_MW} MW)')
    axes[3].set_ylabel('Discharge (MW)', fontsize=11, fontweight='bold')
    axes[3].set_xlabel('Date', fontsize=11, fontweight='bold')
    axes[3].set_ylim(-5, POWER_MW + 5)
    axes[3].grid(True, alpha=0.3, linestyle='--')
    axes[3].legend(loc='upper right')
    
    # Format x-axis
    plt.gcf().autofmt_xdate()
    
    # Add summary text box
    summary_text = (f'Total Revenue: ${total_revenue:,.2f}\n'
                   f'Power: {POWER_MW} MW | Capacity: {ENERGY_MWH} MWh | '
                   f'Efficiency: {EFFICIENCY*100:.0f}%\n'
                   f'Daily Cycle Limit: {MAX_DAILY_THROUGHPUT} MWh')
    
    plt.figtext(0.5, 0.01, summary_text, ha='center', fontsize=10,
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    
    # Save figure
    output_path = os.path.join(script_dir, 'bess_optimization_results.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✓ Visualization saved to: {output_path}")
    
    return output_path


# ============================================================================
# MAIN EXECUTION
# ============================================================================
def main():
    """Main execution function."""
    
    # File path - looks for CSV in the same directory as the script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, 'PRICE_AND_DEMAND_202602_SA1.csv')
    
    # Load and clean data
    df = load_and_clean_data(filepath)
    
    # Run optimization
    results_df, total_revenue = run_optimization(df)
    
    # Create visualization
    viz_path = create_visualization(results_df, total_revenue, script_dir)
    
    # Save detailed results to CSV
    output_csv = os.path.join(script_dir, 'bess_optimization_detailed_results.csv')
    results_df.to_csv(output_csv, index=False)
    print(f"✓ Detailed results saved to: {output_csv}")
    
    print("\n" + "=" * 70)
    print("OPTIMIZATION COMPLETE")
    print("=" * 70)
    print(f"TOTAL REVENUE: ${total_revenue:,.2f}")
    print("=" * 70)
    
    return results_df, total_revenue


if __name__ == "__main__":
    main()
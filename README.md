# BESS Dispatch Optimization - Assessment Submission

## Executive Summary

**Total Revenue: $322,987.17**

This solution optimizes a 100 MW / 200 MWh Battery Energy Storage System (BESS) trading in the South Australian electricity market (SA1) over a 3-day period in February 2026.

### Key Results
- **Day 1 (Feb 6)**: $59,886.37
- **Day 2 (Feb 7)**: $222,718.45 (high price spike to $20,300/MWh)
- **Day 3 (Feb 8)**: $40,382.35
- **Average Daily Revenue**: $107,662.39

## Methodology

### Optimization Approach
I implemented a **Linear Programming (LP)** solution using `scipy.optimize.linprog` with the HiGHS solver. This guarantees globally optimal solutions, unlike greedy algorithms which can miss arbitrage opportunities.

### Mathematical Formulation

**Decision Variables:**
- `charge[t]`: Energy charged in interval t (MWh)
- `discharge[t]`: Energy discharged in interval t (MWh)  
- `soc[t]`: State of charge at end of interval t (MWh)

**Objective Function:**
```
Maximize: Σ(discharge[t] × price[t] - charge[t] × price[t])
```

**Constraints:**
1. **Power limits**: `0 ≤ charge[t], discharge[t] ≤ 100 MW × Δt`
2. **SOC limits**: `0 ≤ soc[t] ≤ 200 MWh`
3. **SOC dynamics**: `soc[t] = soc[t-1] + charge[t] × 0.85 - discharge[t]`
4. **Initial/Final SOC**: `soc[0] = 0, soc[T] = 0` (daily reset)
5. **Throughput limit**: `Σ discharge[t] ≤ 200 MWh` (1 cycle per day)

### Key Implementation Details

1. **Efficiency Application**: The 85% round-trip efficiency is applied during charging. If 100 MWh is charged, only 85 MWh enters storage. Discharging is 100% efficient.

2. **5-Minute Intervals**: The dataset contains 288 intervals per day (24h × 12 intervals/hour). Energy calculations account for the 5-minute (1/12 hour) duration.

3. **Daily Independence**: The battery returns to 0% SOC at midnight, preventing energy carry-over between days.

4. **Cycle Limit Enforcement**: Each day is constrained to ≤200 MWh total discharge (exactly 1 full cycle).

## File Structure

```
bess_optimization.py              
bess_optimization_results.png     
bess_optimization_detailed_results.csv  
README.md                        
requirements.txt                  
```

## Installation & Usage

### Requirements
```bash
pip install pandas numpy scipy matplotlib
```

Or using the provided requirements file:
```bash
pip install -r requirements.txt
```

### Running the Script

**On Windows:**
```bash
python bess_optimization.py
```

**On Mac/Linux:**
```bash
python3 bess_optimization.py
```

The script will automatically:
- Look for the CSV in the same directory
- Create output files in the same directory

### Outputs
1. **Console output**: Daily revenue breakdown and summary statistics
2. **Visualization**: `bess_optimization_results.png` - 4-panel plot showing:
   - Price curve
   - State of Charge
   - Charging activity
   - Discharging activity
3. **Detailed CSV**: `bess_optimization_detailed_results.csv` - Interval-by-interval results

## Results Analysis

### Day 1 (Feb 6, 2026) - $59,886
- Relatively stable pricing ($-185 to $299/MWh)
- Standard arbitrage: charge during low prices, discharge during peaks
- Full cycle utilization (200 MWh throughput)

### Day 2 (Feb 7, 2026) - $222,718
- **Extreme price spike**: $20,300/MWh during evening peak
- Optimizer strategically reserved capacity for high-value discharge
- Demonstrates LP's ability to anticipate and optimize for rare events
- Full cycle utilization targeting the price spike

### Day 3 (Feb 8, 2026) - $40,382
- Moderate volatility ($-8 to $301/MWh)  
- Multiple smaller charge/discharge cycles
- Full cycle utilization

### Key Insights

1. **Price Spike Capture**: The LP algorithm successfully identified and capitalized on the extreme price event on Day 2, generating 69% of total revenue in a single day.

2. **Optimal Throughput**: All three days utilized exactly 200 MWh discharge (100% of allowable cycle), indicating the cycle constraint was binding.

3. **Daily Reset**: SOC returns to 0 MWh at midnight each day, confirming compliance with warranty constraints.

4. **Negative Pricing**: The optimizer correctly handles negative prices (present on all three days), charging when paid to consume.

## Technical Highlights

### Why Linear Programming?

1. **Global Optimality**: Unlike greedy algorithms, LP guarantees the best possible solution
2. **Complex Constraints**: Naturally handles multiple coupled constraints (power, energy, throughput)
3. **Scalability**: Efficient for large time horizons (288 intervals × 3 variables = 864 decision variables)
4. **Industry Standard**: Widely used in energy trading and grid optimization

### Data Quality Checks

The script includes comprehensive validation:
- No missing 5-minute intervals
- No duplicate timestamps  
- Handles negative prices correctly
- Validates SOC bounds and throughput limits

### Code Quality

- **Modular design**: Separate functions for data loading, optimization, and visualization
- **Comprehensive documentation**: Docstrings for all functions
- **Error handling**: Validates optimization success
- **Production-ready**: Can be extended to multi-day, multi-asset portfolios

## Alternative Approaches Considered

1. **Greedy Algorithm**: Simpler but suboptimal. Would miss intra-day arbitrage opportunities.
2. **Dynamic Programming**: More complex, similar results to LP for this convex problem.
3. **Mixed-Integer LP**: Could model discrete charging decisions, but unnecessary here.
4. **Reinforcement Learning**: Overkill for deterministic optimization with perfect foresight.

## Extensions for Production Use

1. **Forecast Integration**: Replace perfect foresight with price forecasts + uncertainty
2. **Multi-day Look-ahead**: Optimize across multiple days with relaxed end-SOC constraints
3. **Degradation Modeling**: Penalize deep cycles and frequent transitions
4. **Market Constraints**: Add minimum dispatch quantities, ramp rates, FCAS co-optimization
5. **Risk Management**: Add CVaR constraints for downside protection

## Asset Parameters Summary

| Parameter | Value |
|-----------|-------|
| Power | 100 MW |
| Energy | 200 MWh (2-hour duration) |
| Round-Trip Efficiency | 85% (applied on charge) |
| Initial SOC | 0% |
| Daily Cycle Limit | 1 full cycle (200 MWh) |

## Author Notes

This implementation prioritizes:
1. **Correctness**: Verified constraint satisfaction and energy balance
2. **Clarity**: Well-documented code suitable for team review
3. **Scalability**: Architecture supports multi-day, multi-asset expansion
4. **Real-world applicability**: Mirrors actual BESS trading optimization problems

The LP formulation closely matches production implementations used by energy traders and battery operators globally. The modular structure allows easy integration with forecast models, real-time data pipelines, and automated trading systems.

---

**Assessment Completion Time**: ~3 hours  
**Primary Tools**: Python, SciPy, Pandas, Matplotlib  

**Optimization Method**: Linear Programming (HiGHS solver)

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, mean_squared_error
from sklearn.model_selection import KFold, cross_val_score
import time
import warnings
warnings.filterwarnings('ignore')
from math import ceil, floor
from Functions.polygon_scrape import *
import datetime as dt
import shap


def RunStrategy(model_estimate_data, dates, trading_days, r, thresh, num_strikes = 1,comparison='mean',results_data=None,verbose=False,verbose_signal=False,export=False, analysis=False):
    '''
    For all date in dates, execute (buy or sell) a straddle using the closest call strike above and closest put strike below to SPY's close. The decision
    to buy or sell the strategy is determined by comparing the model estimate to the markets. If the model estimate is higher, the
    straddle is bought and vice versa.

    Parameters:
    model_estimate: An estimate for volatility that is purportedly able to "beat the market."
    dates: The dates for which the strategy would be bought.
    trading_days: A list of relevant trading days.
    verbose: If True, prints out each result.
    export: If True, saves the results in a .csv. Output becomes [[{'Date','Return', 'Signal', 'Model Estimate', 'Market Estimate'},[return_time_series]]]

    Returns:
    dict: {A dictionary with keys 'Date', 'Return', 'Signal', 'Model Estimate', 'Market Estimate'}, and 'return_time_series' if analysis=True]
    '''
    if (results_data is None) and (comparison != 'mean'):
        raise ValueError('Comparison method must be mean when scraping data.')
    
    results = []

    for date in dates:
        # model_estimate_dict['nominal'] is the un-normalized estimate
        model_estimate_dict = {'nominal':model_estimate_data.loc[date][0]}

        # If results_data are provided, then market estimate can be achieved without pullin from API
        if results_data is not None:
            # Convert date to a datetime object
            date = datetime_to_string(date)
            try:
                #Extract IV information from input data
                data = results_data.loc[date]
                data['Normalized Market Estimate'] = normalize_IV_data(data,results_data,comparison)

            except:
                raise ValueError("Input date not in datetime or suitable string format.")

        # If no results_data are provided, all the necessary information will be pulled from API
        else:
            data = None
        
        # Normalize model RV estimate data
        if comparison=='mean':
            model_estimate_dict['Normalized'] = (model_estimate_dict['nominal']/np.mean(model_estimate_data['values']))
        else:
            model_estimate_dict['Normalized'] = (model_estimate_dict['nominal']/np.median(model_estimate_data['values']))

        # Obtain the results of running the option trading strategy for date
        results.append(OptionStrategy(model_estimate_dict,dt.datetime.strptime(date,'%m/%d/%y').date(),trading_days,r,thresh,num_strikes,verbose_signal,data))

        if verbose is True: print(f'{date}: {results[-1]}')
        
    if export is True: 
        result_df = pd.DataFrame(data=results, index=dates)
        result_df.to_csv('Results/results_'+dt.date.today().strftime('%m/%d/%y')+'.csv')

    if analysis is True:
        # Return_time_series is the sum of daily returns from t=0 to t=i
        return_time_series = []
        for i in range(len(results)):
            return_time_series.append(np.sum([float(d['Return']) for d in results[:i+1]]))
        
        # Determine the cumulative sum over all days the strategy was employed
        total_return = np.sum(d['Return'] for d in results)
        # betting_return = betting_strategy(results)
        
        #Determine the fraction of days where the strategy is bought
        days_strategy_bought = np.sum([d['Signal'] for d in results if d['Signal']==1])
        # print(f'Total return from {dates.iloc[0]}-{dates.iloc[-1]}: ${round(total_return,0)}. Average daily return: {round(total_return/len(dates),2)}%. Daily return variance: {round(np.std([d["Return"] for d in results]),2)}. Fraction of days when strategy is bought: {round(days_strategy_bought/len(dates),4)}')
        return [results,return_time_series]
    
    return results


# def betting_strategy(results):
#     bet = 1
#     rturn = [0]
#     if results[0]['Return'] > 0: last = 'W'
#     else: last = 'L'
#     for i, _ in enumerate(results):
#         if i == 0: bet = 1
#         elif results[i-1]['Return'] < 0: 
#             if last == 'L':
#                 bet=bet*.9
#             else:
#                 bet = 1
#             last = 'L'
#         elif results[i-1]['Return'] > 1: 
#             if last == 'W':
#                 bet = bet*1.1
#             else:
#                 bet = 1
#             last = 'W'
#         rturn.append(
#             rturn[-1] + results[i]['Return']*bet
#         )
#     return rturn
        


def OptionStrategy(model_estimate_dict,date,trading_days,r,thresh,num_strikes=1,verbose=False,data=None):
    '''
    Execute (buy or sell) a straddle using the closest call strike above and closest put strike below to SPY's close. The decision
    to buy or sell the strategy is determined by comparing the model estimate to the markets. If the model estimate is higher, the
    straddle is bought and vice versa.

    Parameters:
    model_estimate: An estimate for volatility that is purportedly able to "beat the market."
    date: The date for which the strategy would be bought.
    trading_days: A list of relevant trading days.
    verbose: If True prints the trade signal where 1=buy and -1=sell.
    data: If None, pull

    Returns:
    dict: {'Date','Return', 'Signal', 'Model Estimate', 'Market Estimate'}
    '''
    #If no result data are provided, data is pulled from API
    if data is None:
        #Get the avg IV of the lower strike put and higher strike call, and the SPY close price for date and the next trading day
        result = calculate_IV(date,trading_days,r,num_strikes)

        cc = result['call_close'][0]
        pc = result['put_close'][0]
        sc = result['stock_close']
        sc_next = result['stock_close_next']
        market_estimate = result['avg_IV']

        #Normalize the market estimate based on historical average and std deviation from 4/1/19 to 8/10/23 (See Data/Summary_Stats_for_IV_Data.ipynb)
        normalized_market_estimate = result['avg_IV'] / .26

        #If implied vol does not suggest a move past the first strike in each direction, trade cannot work
        if (ceil(sc*(1+market_estimate/sqrt(365))) == ceil(sc)) or (floor(sc*(1-market_estimate/sqrt(365))) == floor(sc)):
            return(f"IV too small to trade: {market_estimate}")

        #Determine if the strategy should be bought or sold based on the model's prediction.
        #If model_estimate_dict is not a dictionary, it should be an integer. This represents when the function is run with
        #only a single model estimate and not a list. Thus, the estiamte cannot be normalized to the list average/median.
    

        if isinstance(model_estimate_dict, dict):
            signal = GetSignal(model_estimate_dict['Normalized'],normalized_market_estimate,thresh)
        elif isinstance(model_estimate_dict, (int, float)):
            signal = GetSignal((model_estimate_dict/.124),normalized_market_estimate,thresh)
            model_estimate_dict = {'nominal':model_estimate_dict}
        else:
            raise ValueError(f'Model estimate value invalid: {model_estimate_dict}')

        #Find how many calls (x) and how many puts (y) should be purchased for the strategy
        x,y = GetRatiosUnbounded(sc,cc,pc,market_estimate)

        if (x > 20) or (y > 20):
            return(f"Solution too large: {round(x,2)} calls and {round(y,2)} puts.")
        if (x < 0) or (y < 0):
            return(f"IV too small to trade: {market_estimate}")
        
        #profit = +- (payoff from x calls + payoff from y puts - initial cost)
        payoff_calls = x*max(sc_next - ceil(sc),0)
        payoff_puts = y*max(floor(sc)-sc_next,0)
        initial_cost = (x*cc + y*pc)*np.exp(-.05375/365)

        profit = signal * (payoff_calls + payoff_puts - initial_cost)
        Return = round(profit/initial_cost*100,2)

        return{'Return': Return, 'Signal': signal, 'Model Estimate': model_estimate_dict['nominal'], 'Market Estimate': market_estimate, 'num_puts': y}
    
    #If result data is provided, API is not used
    else:
        signal = GetSignal(model_estimate_dict['Normalized'],data['Normalized Market Estimate'],thresh)
        if verbose is True: 
            if signal == 1: print(f'{date}')
        Return = signal * data['Return [%]']

        return {'Date':date,'Return': Return, 'Signal': signal, 'Model Estimate': model_estimate_dict, 'Market Estimate': data['Avg IV']}
    

def RollingWindowRF(X,Y,dates,w=300,n_trees=200,msl=2,md=12,method='mse',mf=None,SHAP=False):
    '''
    For timeseries data: fit the previous w days using a random forest model to predict the next day. Repeat for range(w+1,len(X)).

    Parameters:
    X: Predictor dataframe.
    Y: Target variable dataframe.
    dates: Series containing dates corresponding to X and Y data.
    w: Length of the rolling window--how many days back does the model fit to.
    method: Optimization method for sklearn.linearmodel.LinearRegression.

    Returns:
    dict: {'predictions', 'mse', 'mape','runtime', 'feature importance'}
    '''
    if len(X) != len(Y):
        raise ValueError("X and Y are not the same length")
    
    if len(X) < w:
        raise ValueError("Window size is larger than dataset")

    try:
        RandomForestRegressor(criterion=method).fit([0,1],[1,2])
    except:
        method = {'mse': 'squared_error', 'mae': 'absolute_error'}[method]

    if mf is None:
        mf = len(X.columns)

    start = time.time()

    feature_importance = pd.DataFrame(index=X.columns, columns=dates[w:])
    predictions = pd.DataFrame(index=['values'],columns=dates[w:])
    shap_values_df = pd.DataFrame()
    
    for t in range(w,len(X)):
        x_train = X.iloc[t-w:t]
        y_train = Y.iloc[t-w:t]

        rf = RandomForestRegressor(n_estimators=n_trees, random_state=10,min_samples_leaf=msl, max_features=mf, 
                                   max_depth=md,min_samples_split=2, n_jobs=-1,criterion=method).fit(x_train,y_train)

        predictions[dates[t]] = rf.predict([X.iloc[t]])[0]
        feature_importance[dates[t]] = rf.feature_importances_

        if SHAP is True:
            explainer = shap.Explainer(rf)
            shap_values = explainer.shap_values(X.iloc[t])
            shap_values_df = pd.concat([shap_values_df, pd.Series(shap_values)],axis=1)


    mse = mean_squared_error(predictions.loc['values'],Y.iloc[w:])
    mape = mean_absolute_percentage_error(predictions.loc['values'],Y.iloc[w:])
    relative_r_sqr = 1 - mse/(1.859e-8) # denominator is baseline for HAR w=300, date range 8/23/18-8/10/23
    if SHAP is True:
        feature_importance = shap_values_df.values
    fin = time.time() - start

    return {'predictions': predictions, 'mse': mse, 'mape': mape, 'relative_r_squared': relative_r_sqr, 'runtime': fin, 'feature_importance': feature_importance}


def RollingWindowHAR(X,Y,dates,w=300):
    '''
    For timeseries data: fit the previous w days using the linear HAR model to predict the next day. Repeat for range(w+1,len(X)).

    Parameters:
    X: Predictor dataframe.
    Y: Target variable dataframe.
    dates: Series containing dates corresponding to X and Y data.
    w: Length of the rolling window--how many days back does the model fit to.
    method: Optimization method for sklearn.linearmodel.LinearRegression.

    Returns:
    dict: {'predictions', 'mse', 'mape','runtime', 'betas'}
    '''
    if len(X) != len(Y):
        raise ValueError("X and Y are not the same length")
    
    if len(X) < w:
        raise ValueError("Window size is larger than dataset")
    
    start = time.time()

    betas = pd.DataFrame(index=X.columns, columns=dates[w:])
    predictions = pd.DataFrame(index=['values'],columns=dates[w:])
    
    for t in range(w,len(X)):
        x_train = X.iloc[t-w:t]
        y_train = Y.iloc[t-w:t]

        lr = LinearRegression(n_jobs=-1).fit(x_train,y_train)

        predictions[dates[t]] = lr.predict([X.iloc[t]])[0]
        betas[dates[t]] = [lr.intercept_].append(lr.coef_)

    mse = mean_squared_error(predictions.loc['values'],Y.iloc[w:])
    mape = mean_absolute_percentage_error(predictions.loc['values'],Y.iloc[w:])

    fin = time.time() - start

    return {'predictions': predictions, 'mse': mse, 'mape': mape, 'runtime': fin, 'betas': betas, 'model': lr}


def GetSignal(model,market,thresh):
    '''
    Determine whether to buy or sell the straddle strategy. If the model prediction is higher than the market's, the strategy
    is bought and vice versa.
    '''
    if model >= thresh * market:
        return(1)
    else:
        return(-1)
    
    
def GetRatiosUnbounded(sc,cc,pc,avg_IV):
    '''
    Determine the ratio of calls/puts to buy such that the option strategy breaks even with the market's estimate for 
    next day's vol. Solution is a ratio and normalized such that the # of calls is 1.
    sc: Today's SPY closing price.
    cc: Today's closing price for the closest above call strike expiring the next day.
    pc: Today's closing price for the closest below put strike expiring the next day.
    avg_IG: The market's estimate for next day vol based on the average IV of the closest above and below call and put strikes respectively (see IV_grab in polygonscrape.py).
    Output: (#calls, #puts)
    '''
    from scipy.optimize import fsolve
    def func(x):
        return (floor(sc) - (cc*x[0]+pc*x[1])/x[1]) - sc*(1-avg_IV/sqrt(365)), (ceil(sc) + (cc*x[0]+pc*x[1])/x[0]) - sc*(1+avg_IV/sqrt(365))
    sol = fsolve(func,[1,1],factor=.1,maxfev=5000)
    return 1, sol[1]/sol[0]


def datetime_to_string(date):
    if isinstance(date, (dt.date, dt.datetime)) is True:
        try:
            return dt.datetime.strftime(date,'%m/%d/%y')
        except:
            raise ValueError("Input date not in datetime or suitable string format.")
    else:
        return date
    

def normalize_IV_data(data,results_data,comparison):
    '''Normalizes an Implied Volatility value to its mean or median relative to historical data'''
    if comparison=='mean':
        return (data['Avg IV']/np.mean(results_data['Avg IV']))
    else: 
        return (data['Avg IV']/np.median(results_data['Avg IV']))
    

##############################
# Not fully functional, ignore
##############################


# def RollingWindowRF_Resample(X,Y,dates,w=300,n_trees=200,method='mse'):
#     '''
#     For timeseries data: fit the previous w days using a random forest model to predict the next day. Repeat for range(w+1,len(X)).

#     Parameters:
#     X: Predictor dataframe.
#     Y: Target variable dataframe.
#     dates: Series containing dates corresponding to X and Y data.
#     w: Length of the rolling window--how many days back does the model fit to.
#     method: Optimization method for sklearn.linearmodel.LinearRegression.

#     Returns:
#     dict: {'predictions', 'mse', 'mape','runtime', 'feature importance'}
#     '''
#     if len(X) != len(Y):
#         raise ValueError("X and Y are not the same length")
    
#     if len(X) < w:
#         raise ValueError("Window size is larger than dataset")

#     try:
#         RandomForestRegressor(criterion=method).fit([0,1],[1,2])
#     except:
#         method = {'mse': 'squared_error', 'mae': 'absolute_error'}[method]

#     start = time.time()

#     feature_importance = pd.DataFrame(index=X.columns, columns=dates[w:])
#     predictions = pd.DataFrame(index=['values'],columns=dates[w:])
    
#     for t in range(w,len(X)):
#         X_w = X.iloc[t-w:t]
#         y_w = Y.iloc[t-w:t]

#         kf = KFold(n_splits=10)

#         models = []
#         scores = []
#         for train_index, val_index in kf.split(X_w):
#             X_train, X_val = X_w.iloc[train_index], X_w.iloc[val_index]
#             y_train, y_val = y_w.iloc[train_index], y_w.iloc[val_index]
#             model = RandomForestRegressor(n_estimators=n_trees, random_state=10,min_samples_leaf=2, max_features=len(X.columns), 
#                                    max_depth=12,min_samples_split=2, n_jobs=-1,criterion=method)
#             model.fit(X_train, y_train)
#             models.append(model)
#             scores.append(model.score(X_val, y_val))
        
#         best_model = models[scores.index(max(scores))]

#         predictions[dates[t]] = best_model.predict([X.iloc[t]])[0]
#         feature_importance[dates[t]] = best_model.feature_importances_

#     mse = mean_squared_error(predictions.loc['values'],Y.iloc[w:])
#     mape = mean_absolute_percentage_error(predictions.loc['values'],Y.iloc[w:])
#     relative_r_sqr = 1 - mse/(1.859e-8) # denominator is baseline for HAR w=300, date range 8/23/18-8/10/23
#     fin = time.time() - start

#     return {'predictions': predictions, 'mse': mse, 'mape': mape, 'relative_r_squared': relative_r_sqr, 'runtime': fin, 'feature_importance': feature_importance}
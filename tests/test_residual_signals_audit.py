"""Independent synthetic causal/statistical-contract audit; no market data."""
import numpy as np
import pandas as pd
import pytest
from examples.residual_convergence import signals as model


@pytest.fixture
def synthetic_training():
    index=pd.date_range(model.START+pd.Timedelta(hours=1,minutes=1),
                        model.TRAIN_END-pd.Timedelta(hours=1)+pd.Timedelta(minutes=1),freq='h')
    rng=np.random.default_rng(901)
    log_b=np.cumsum(rng.normal(0,.002,len(index)))
    log_e=np.cumsum(rng.normal(0,.002,len(index)))
    elapsed=np.arange(len(index),dtype=float)
    prices={'BTCUSDT':20000*np.exp(log_b),'ETHUSDT':1000*np.exp(log_e)}
    first=np.flatnonzero(index>=model.BETA_END)[0]
    for k,alt in enumerate(model.ALTS):
        x=np.zeros(len(index))
        for i in range(first+1,len(index)):x[i]=.85*x[i-1]+rng.normal(0,.001)
        prices[alt]=(.01+k)*np.exp(.7*log_b+.2*log_e+.00001*elapsed+x)
    return pd.DataFrame(prices,index=index)[model.SYMBOLS]


@pytest.fixture
def fixed_adf(monkeypatch):
    calls=[]
    def adf(values,**kwargs):
        calls.append((np.array(values,copy=True),kwargs))
        return (-8.,.001,24,len(values)-25,{'1%':-3.43,'5%':-2.86,'10%':-2.57})
    monkeypatch.setattr('statsmodels.tsa.stattools.adfuller',adf)
    return calls


def test_fit_disjoint_windows_and_no_endpoint_constraint(synthetic_training,fixed_adf):
    frame=synthetic_training;alt=model.ALTS[0]
    fitted=model.fit_asset(frame,alt)
    assert fitted['beta_btc']==pytest.approx(.7,abs=1e-10)
    assert fitted['beta_eth']==pytest.approx(.2,abs=1e-10)
    assert fitted['alpha']==pytest.approx(.00001,abs=1e-12)
    d=fitted['diagnostics']
    assert pd.Timestamp(d['beta_last_available_at'])<model.BETA_END
    assert pd.Timestamp(d['calibration_first_available_at'])>=model.BETA_END
    assert pd.Timestamp(d['calibration_last_available_at'])<model.TRAIN_END
    assert pd.Timestamp(fitted['origin_price_time'])==model.BETA_END
    assert abs(d['calibration_terminal_residual'])>1e-6
    changed=frame.copy()
    mask=changed.index>=model.BETA_END
    changed.loc[mask,alt]*=np.exp(np.linspace(0,1,mask.sum()))
    other=model.fit_asset(changed,alt)
    for key in ['alpha','beta_btc','beta_eth']:
        assert other[key]==fitted[key]
    assert other['diagnostics']['calibration_terminal_residual']!=pytest.approx(d['calibration_terminal_residual'])


def test_future_invalid_rows_cannot_change_training_fit(synthetic_training,fixed_adf):
    baseline=model.fit_models(synthetic_training)
    future=pd.DataFrame(np.nan,index=pd.date_range(model.TRAIN_END+pd.Timedelta(minutes=1),periods=3,freq='h'),columns=model.SYMBOLS)
    future.iloc[1,:]=-1;future.iloc[2,:]=np.inf
    assert model.fit_models(pd.concat([synthetic_training,future]))==baseline
    assert model.fit_asset(pd.concat([synthetic_training,future]),model.ALTS[0])==baseline['assets'][model.ALTS[0]]


def test_pinned_adf_no_autolag_and_failed_diagnostic_stays_no_trade(synthetic_training,fixed_adf,monkeypatch):
    fitted=model.fit_models(synthetic_training)
    assert len(fixed_adf)==6
    for values,kwargs in fixed_adf:
        assert kwargs=={'maxlag':24,'regression':'c','autolag':None}
        assert values[0]==pytest.approx(0.,abs=1e-12)
        assert abs(values[-1])>1e-8
    monkeypatch.setattr('statsmodels.tsa.stattools.adfuller',lambda values,**kwargs:(0.,.9,24,len(values)-25,{}))
    failed=model.fit_models(synthetic_training)
    assert all(not item['eligible'] and 'conditional_adf' in item['diagnostics']['failed_checks'] for item in failed['assets'].values())
    features=model.build_features(synthetic_training.tail(20),failed)
    assert features.filter(like='z_').isna().all().all()


def test_hourly_calibration_grid_missing_duplicate_rejected(synthetic_training,fixed_adf):
    for invalid in [synthetic_training.drop(synthetic_training.index[100]),
                    pd.concat([synthetic_training.iloc[:101],synthetic_training.iloc[100:]])]:
        with pytest.raises(ValueError):model.fit_asset(invalid,model.ALTS[0])


@pytest.mark.parametrize('bad',[0.,-1.,np.nan,np.inf])
def test_bad_training_price_is_not_hidden_by_future_filter(synthetic_training,fixed_adf,bad):
    frame=synthetic_training.copy();frame.iloc[100,2]=bad
    with pytest.raises(ValueError,match='finite positive'):model.fit_asset(frame,model.ALTS[0])


def test_collinear_factors_never_become_eligible(synthetic_training,fixed_adf):
    frame=synthetic_training.copy();frame['ETHUSDT']=frame['BTCUSDT']*.05
    result=model.fit_asset(frame,model.ALTS[0])
    assert not result['eligible']
    assert 'identified_beta' in result['diagnostics']['failed_checks']


def known_model():
    origin=model.BETA_END+pd.Timedelta(minutes=1)
    item={'eligible':True,'alpha':.006,'beta_btc':.7,'beta_eth':.2,
          'origin_available_at':str(origin),'origin_price_time':str(model.BETA_END),
          'origin_prices':{s:10. for s in model.SYMBOLS},'mu':.01,'sigma':.02,'phi':.85}
    return {'assets':{alt:dict(item) for alt in model.ALTS}}


def test_minute_alpha_hour_units_constant_origin_and_prefix_future_invariance():
    models=known_model()
    index=pd.date_range(model.TRAIN_END+pd.Timedelta(minutes=1),periods=121,freq='min')
    frame=pd.DataFrame(10.,index=index,columns=model.SYMBOLS)
    original=model.build_features(frame,models)
    alt=model.ALTS[0]
    assert original[f'x_{alt}'].iloc[60]-original[f'x_{alt}'].iloc[0]==pytest.approx(-.006)
    assert original[f'x_{alt}'].iloc[0]!=0  # no reset at the April wallet boundary
    cut=67
    pd.testing.assert_frame_equal(model.build_features(frame.iloc[:cut],models),original.iloc[:cut])
    pd.testing.assert_frame_equal(model.build_features(frame.iloc[60:],models),original.iloc[60:])
    future=frame.copy();future.iloc[cut:]*=np.exp(np.linspace(0,3,len(frame)-cut))[:,None]
    pd.testing.assert_frame_equal(model.build_features(future,models).iloc[:cut],original.iloc[:cut])
    # Constant bundle-price unit change cancels in log returns when origin uses the same native unit.
    pepe='PEPEUSDT';scaled=frame.copy();scaled[pepe]*=1000
    adjusted=known_model();adjusted['assets'][pepe]['origin_prices']=dict(adjusted['assets'][pepe]['origin_prices']);adjusted['assets'][pepe]['origin_prices'][pepe]*=1000
    pd.testing.assert_series_equal(model.build_features(scaled,adjusted)[f'x_{pepe}'],original[f'x_{pepe}'])


def test_tradable_z_unavailable_before_calibration_completes():
    models=known_model()
    frame=pd.DataFrame(10.,index=pd.DatetimeIndex([model.BETA_END+pd.Timedelta(minutes=1),model.TRAIN_END-pd.Timedelta(minutes=1)]),columns=model.SYMBOLS)
    assert model.build_features(frame,models).filter(like='z_').isna().all().all()


def test_hourly_prices_uses_completed_hour_availability():
    index=pd.date_range(model.BETA_END+pd.Timedelta(minutes=1),periods=121,freq='min')
    frame=pd.DataFrame(np.arange(121)[:,None]+np.ones((121,8))*10,index=index,columns=model.SYMBOLS)
    hourly=model.hourly_prices(frame)
    pd.testing.assert_frame_equal(hourly,frame.iloc[[0,60,120]])


def test_known_ar1_recovers_parameters_without_forcing_endpoint_zero():
    rng=np.random.default_rng(3);values=np.zeros(10000)
    for i in range(1,len(values)):values[i]=.001+.85*values[i-1]+rng.normal(0,.002)
    result=model.fit_ou(values)
    assert result['valid'] and result['phi']==pytest.approx(.85,abs=.02)
    assert result['mu']==pytest.approx(.001/(1-.85),abs=.0005)
    assert result['sigma']==pytest.approx(.002/np.sqrt(1-.85**2),rel=.08)
    assert result['half_life_hours']==pytest.approx(-np.log(2)/np.log(.85),rel=.15)
    assert values[-1]!=0


@pytest.mark.parametrize('values',[np.ones(1000),(-1.)**np.arange(1000),1.003**np.arange(1000)])
def test_non_ou_residual_does_not_get_clipped_into_validity(values):
    assert not model.fit_ou(values)['valid']


def test_deterministic_linear_drift_not_mistaken_for_intraday_reversion():
    result=model.fit_ou(np.arange(1000,dtype=float))
    # Roundoff can put the exactly unit AR coefficient infinitesimally below1.
    assert not result['valid'] or result['half_life_hours']>24

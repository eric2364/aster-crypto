"""Independent publication guard and displayed-scope adversaries."""
from pathlib import Path
import pandas as pd
import pytest
from examples.funding_rank import publish as p
from examples.funding_rank import run as r
from test_funding_rank_publisher import packet


@pytest.mark.parametrize('target',['financial_complete','feature_complete','policy','trajectory','gates_reconstructed'])
def test_truthy_nonboolean_proof_cannot_authorize_publication(packet,target):
    out,a,b,_,fp,_=packet;first=next(iter(a['phases']))
    if target=='financial_complete':a['complete']=1
    elif target=='feature_complete':b['complete']='true'
    elif target=='policy':a['phases'][first]['recorded_policy_intents']['recorded_policy_reconstruction_passed']=1
    elif target=='trajectory':a['phases'][first]['trajectory_reconstruction_passed']='true'
    else:a['gates_reconstructed']=1
    with pytest.raises(RuntimeError):p.verify_receipts(None,out,a,b,r.digest(fp))


def test_extra_resealed_output_or_hidden_phase_cannot_extend_research_scope(packet):
    out,a,b,_,fp,_=packet;first=next(iter(a['phases']))
    a['phases'][first]['outputs_sha256']['selected_profitable_subset.csv']='0'*64
    with pytest.raises(RuntimeError):p.verify_receipts(None,out,a,b,r.digest(fp))
    a['phases'][first]['outputs_sha256'].pop('selected_profitable_subset.csv')
    (out/'trials/validation_neighbor').mkdir()
    with pytest.raises(RuntimeError):p.verify_receipts(None,out,a,b,r.digest(fp))


def test_resealed_summary_cannot_relabel_same_path_as_fresh_holdout(packet):
    out,a,b,_,fp,_=packet;summary=r.read(out/'summary.json')
    summary['research_status']='fresh untouched holdout';r.dump(out/'summary.json',summary)
    a['summary_sha256']=r.digest(out/'summary.json')
    with pytest.raises(RuntimeError):p.verify_receipts(None,out,a,b,r.digest(fp))


def test_publication_never_adds_files_to_immutable_input_namespace(packet,tmp_path):
    out,a,b,ap,fp,_=packet;cache=tmp_path/'sealed_cache';cache.mkdir()
    (cache/'raw.receipt').write_bytes(b'preserved')
    with pytest.raises(RuntimeError):p.publish(cache,out,cache/'publication',ap,fp)
    assert {x.name for x in cache.iterdir()}=={'raw.receipt'}


def test_render_all_leg_losses_aborts_and_rejected_selections_distinct(packet):
    out,a,b,_,_,_=packet;folder=out/'trials/evaluation'
    legs=pd.read_csv(folder/'leg_contributions.csv');legs.loc[legs.symbol.eq('PEPEUSDT'),'net_pnl']=-321.5
    legs.to_csv(folder/'leg_contributions.csv',index=False)
    r.dump(folder/'strategy_diagnostics.json',{'events':[{'type':'ACCOUNT_ABORT'}]})
    r.dump(folder/'proposal_ledger.json',[{'type':'WEEKLY_PROPOSAL'},{'type':'PROPOSAL_REJECTED'}])
    page,scores,rendered,activity=p.build_report(out,r.read(out/'summary.json'))
    row=next(x for x in activity if x['phase']=='evaluation')
    assert row['abort_events']==1 and row['weekly_proposals']==1 and row['rejected_weekly_proposals']==1
    assert len(rendered)==40 and next(x for x in rendered if x['phase']=='evaluation' and x['symbol']=='PEPEUSDT')['net_pnl']==-321.5
    assert '-321.50' in page and 'omitted unlogged skips' in page and 'not high-frequency arbitrage' in page

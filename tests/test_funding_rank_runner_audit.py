"""Independent synthetic packet/cache adversaries; no historical data access."""
import copy
import pytest
from examples.funding_rank import run as r
from test_funding_rank_runner import frozen, sealed_trial, good_scores


@pytest.mark.parametrize('kind',['bounds','catalog','manifest_export','manifest_metadata','seal_extra','seal_missing'])
def test_resealed_packet_identity_cannot_replace_reviewed_execution(frozen,kind):
    _,cache,out=frozen
    (out/'features.parquet').write_bytes(b'synthetic feature bytes')
    r.dump(out/'feature_receipt.json',{})
    phase=r.PHASES[0];dest=sealed_trial(cache,out,phase)
    meta=r.read(dest/'metadata.json')
    if kind=='bounds':meta['end']=str(phase[2]+r.pd.Timedelta(minutes=1))
    elif kind=='catalog':meta['instruments'][3]['base']='PEPE'
    elif kind=='manifest_metadata':meta['source_manifest']['funding_boundary']='retroactive future final rate'
    elif kind=='manifest_export':r.dump(dest/'source_manifest.json',{'source_lock':{}})
    r.dump(dest/'metadata.json',meta)
    receipt=r.read(dest/'completion.json');receipt['outputs_sha256']=r.output_files(dest)
    if kind=='seal_extra':receipt['outputs_sha256']['unreviewed_winner.csv']='0'*64
    elif kind=='seal_missing':receipt['outputs_sha256'].pop('terminal_orders.json')
    r.dump(dest/'completion.json',receipt)
    with pytest.raises(RuntimeError):r.verify_completed(cache,out,phase)


def test_strict_terminal_native_dust_and_live_orders_override_empty_core_positions():
    observed={f'quantity_{s}':0. for s in r.SYMBOLS}
    assert r.terminal_status(observed,[])['terminal_flat_resolved'] is True
    observed['quantity_PEPEUSDT']=1e-14
    assert r.terminal_status(observed,[])['terminal_flat_resolved'] is False
    observed['quantity_PEPEUSDT']=0.
    assert r.terminal_status(observed,[{'status':'partial','reduce_only':True}])['terminal_flat_resolved'] is False
    observed['quantity_BTCUSDT']=float('nan')
    with pytest.raises(RuntimeError):r.terminal_status(observed,[])


def test_terminal_gate_requires_literal_proof_not_truthy_annotation():
    scores=good_scores();participants={'BTCUSDT','DOGEUSDT','PEPEUSDT','ADAUSDT'}
    for truthy in ('true',1,{'flat':True}):
        altered=copy.deepcopy(scores);altered['evaluation_stress']['terminal_flat_resolved']=truthy
        gates=r.gate_results(altered,[.01,.02,.03],participants,2)[2]
        assert gates['actual_terminal_flat_all_five_runs'] is False

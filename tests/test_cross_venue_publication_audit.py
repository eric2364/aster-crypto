"""Independent adversarial publication guards, exclusively synthetic receipts."""
import pytest
from examples.cross_venue import publish as p
from examples.cross_venue import run as r
from test_cross_venue_publisher import packet  # shared synthetic artifact factory only

GATES={'positive_compounded_validation','positive_validation_after_exit_reserve','two_positive_anchored_months',
       'daily_sharpe_at_least_half','minute_drawdown_at_most_twenty_percent','no_liquidation_all_seven_runs',
       'four_matched_pairs_including_both_doge_and_pepe'}|{
       'positive_'+name+suffix for name in ('evaluation','evaluation_stress','evaluation_alternative','evaluation_alternative_stress')
       for suffix in ('','_after_exit_reserve')}


@pytest.mark.parametrize('change',['empty','missing','extra','nonboolean'])
def test_all_fifteen_declared_gate_fields_are_required_even_when_resealed(packet,change):
    out,financial,feature,fp,xp,calls=packet
    p.verify_receipts('binance','bybit',out,financial,feature,r.read(out/'no_admission_audit.json'))
    summary=r.read(out/'summary.json');summary['gates']={key:False for key in GATES}
    if change=='empty':summary['gates']={}
    elif change=='missing':summary['gates'].pop('no_liquidation_all_seven_runs')
    elif change=='extra':summary['gates']['redefined_easier_hurdle']=False
    else:summary['gates']['daily_sharpe_at_least_half']='false'
    summary['passes_hurdles']=all(summary['gates'].values())
    r.dump(out/'summary.json',summary);financial['summary_sha256']=r.digest(out/'summary.json')
    cohort=r.read(out/'no_admission_audit.json');cohort['summary_sha256']=financial['summary_sha256']
    with pytest.raises(RuntimeError,match='Exact15 Boolean gates required'):
        p.verify_receipts('binance','bybit',out,financial,feature,cohort)


def test_publisher_own_source_change_after_build_cannot_mislabel_executed_code(packet,tmp_path,monkeypatch):
    out,financial,feature,fp,xp,calls=packet
    source=tmp_path/'publisher.py';source.write_text('source-before-report-build')
    monkeypatch.setattr(p,'__file__',str(source))
    original=p.build_report;built=[]
    def changed(*args):
        report=original(*args);built.append(True);source.write_text('changed-code-after-report-build');return report
    monkeypatch.setattr(p,'build_report',changed)
    destination=tmp_path/'publication'
    with pytest.raises(RuntimeError):p.publish('binance','bybit',out,destination,fp,xp,out/'no_admission_audit.json')
    assert built==[True]
    assert not destination.exists() and not list(tmp_path.glob('.publication-staged-*'))


@pytest.mark.parametrize('subfolder',['trials/extra_report','executed_source/extra_report'])
def test_publication_cannot_mutate_its_sealed_experiment_namespace(packet,subfolder):
    out,financial,feature,fp,xp,calls=packet
    destination=out/subfolder
    p.verify_receipts('binance','bybit',out,financial,feature,r.read(out/'no_admission_audit.json'))
    before={str(path.relative_to(out)):r.digest(path) for path in out.rglob('*') if path.is_file()}
    with pytest.raises(RuntimeError):p.publish('binance','bybit',out,destination,fp,xp,out/'no_admission_audit.json')
    after={str(path.relative_to(out)):r.digest(path) for path in out.rglob('*') if path.is_file()}
    assert after==before and not destination.exists()
    assert {path.name for path in (out/'trials').iterdir()}=={phase[0] for phase in r.PHASES}

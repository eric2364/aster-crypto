"""Independent synthetic publication boundary/provenance adversaries."""
from pathlib import Path
import pytest
from examples.positioning_research import publish as p
from tests.test_positioning_publisher import packet
r=p.r


def test_actual_individual_certificate_schema_is_supported_and_scope_preserved(packet,tmp_path):
    out,fin,feat,policy=packet
    value=r.read(fin);value.pop('common_artifacts_sha256');r.dump(fin,value)
    scoped=r.read(policy);scoped['financial_audit_sha256']=r.digest(fin);r.dump(policy,scoped)
    destination=tmp_path/'report'
    p.publish('synthetic-perp','synthetic-metrics',out,destination,fin,feat,policy)
    assert r.read(destination/'financial_audit.json')['publication_ready'] is False
    assert r.read(destination/'recorded_policy_audit.json')['policy_reconstruction_complete'] is False
    assert len(__import__('pandas').read_csv(destination/'all_leg_contributions.csv'))==40


def test_staged_report_change_after_manifest_hashing_must_not_promote(packet,tmp_path,monkeypatch):
    out,fin,feat,policy=packet;destination=tmp_path/'report';original=r.dump
    def corrupt(path,value):
        original(path,value)
        if Path(path).name=='publication_manifest.json':
            report=Path(path).parent/'report.html';report.write_bytes(report.read_bytes()+b' changed after manifest')
    monkeypatch.setattr(r,'dump',corrupt)
    with pytest.raises(RuntimeError,match='Staged|staged|manifest|publication'):
        p.publish('synthetic-perp','synthetic-metrics',out,destination,fin,feat,policy)
    assert not destination.exists() and not list(tmp_path.glob('.report-*'))

@pytest.mark.parametrize('artifact',['report.html','comparison.csv','financial_audit.json','executed_publisher.py'])
def test_copied_or_generated_artifact_change_after_copy_check_is_rejected(packet,tmp_path,monkeypatch,artifact):
    out,fin,feat,policy=packet;destination=tmp_path/'report';original=r.dump
    def corrupt(path,value):
        original(path,value)
        if Path(path).name=='publication_manifest.json':
            target=Path(path).parent/artifact;target.write_bytes(target.read_bytes()+b' changed')
    monkeypatch.setattr(r,'dump',corrupt)
    with pytest.raises(RuntimeError):p.publish('synthetic-perp','synthetic-metrics',out,destination,fin,feat,policy)
    assert not destination.exists() and not list(tmp_path.glob('.report-*'))


def test_transitive_rendering_helper_changes_during_build_are_rejected(packet,tmp_path,monkeypatch):
    out,fin,feat,policy=packet;destination=tmp_path/'report'
    source=tmp_path/'presentation_helper.py';source.write_bytes(Path(p.REPORT_HELPER).read_bytes());monkeypatch.setattr(p,'REPORT_HELPER',source)
    original=p.build_report
    def mutate(*args):
        result=original(*args);source.write_bytes(source.read_bytes()+b'\n# changed loaded helper');return result
    monkeypatch.setattr(p,'build_report',mutate)
    with pytest.raises(RuntimeError,match='changed'):p.publish('synthetic-perp','synthetic-metrics',out,destination,fin,feat,policy)
    assert not destination.exists()

@pytest.mark.parametrize('gate_change',[{}, {'invented':False}, {k:0 for k in p.GATES}])
def test_resealed_gate_shape_cannot_summarize_a_truncated_packet(packet,gate_change):
    out,fin,feat,policy=packet;summary=r.read(out/'summary.json');summary['gates']=gate_change
    summary['failed_gates']=[k for k,v in gate_change.items() if not v];summary['passes_hurdles']=all(gate_change.values())
    r.dump(out/'summary.json',summary);f=r.read(fin);q=r.read(policy)
    f['summary_sha256']=q['summary_sha256']=r.digest(out/'summary.json');f['common_artifacts_sha256']['summary.json']=f['summary_sha256']
    r.dump(fin,f);q['financial_audit_sha256']=r.digest(fin);r.dump(policy,q)
    with pytest.raises(RuntimeError,match='fifteen Boolean'):p.verify_receipts('p','m',out,fin,feat,policy)

@pytest.mark.parametrize('kind',['publisher','report_helper'])
def test_initial_snapshot_enumeration_cannot_relabel_executing_source(packet,tmp_path,monkeypatch,kind):
    out,fin,feat,policy=packet;destination=tmp_path/'report'
    source=tmp_path/'executing_source.py';source.write_bytes(Path(p.__file__ if kind=='publisher' else p.REPORT_HELPER).read_bytes())
    monkeypatch.setattr(p,'__file__' if kind=='publisher' else 'REPORT_HELPER',str(source) if kind=='publisher' else source)
    original=p.financial_reference.evidence_hashes;calls=[]
    def mutate(*args):
        value=original(*args);calls.append(1)
        if len(calls)==1:source.write_bytes(source.read_bytes()+b'\n# changed during initial evidence enumeration')
        return value
    monkeypatch.setattr(p.financial_reference,'evidence_hashes',mutate)
    with pytest.raises(RuntimeError,match='changed|drift|differ'):p.publish('synthetic-perp','synthetic-metrics',out,destination,fin,feat,policy)
    assert not destination.exists()

@pytest.mark.parametrize('kind',['extra_file','forged_manifest'])
def test_stage_namespace_and_manifest_claims_cannot_change_during_manifest_write(packet,tmp_path,monkeypatch,kind):
    out,fin,feat,policy=packet;destination=tmp_path/'report';original=r.dump
    def corrupt(path,value):
        original(path,value)
        if Path(path).name=='publication_manifest.json':
            if kind=='extra_file':(Path(path).parent/'unsealed_result.csv').write_text('winner,9999\n')
            else:
                altered=r.read(path);altered['qualified_historical_count']=28;original(path,altered)
    monkeypatch.setattr(r,'dump',corrupt)
    with pytest.raises(RuntimeError):p.publish('synthetic-perp','synthetic-metrics',out,destination,fin,feat,policy)
    assert not destination.exists()

import pandas as pd
import pytest
from reconciliation import reconcile, Config

def df(rows): return pd.DataFrame(rows,columns=['거래ID','거래일자','거래처','금액'])

def test_exact_and_date_shift():
    a=df([('L1','2026-11-01','A',100),('L2','2026-11-03','B',200)])
    b=df([('B1','2026-11-01','A',100),('B2','2026-11-04','B',200)])
    s,m,r,d=reconcile(a,b)
    assert set(m['분류'])=={'정확 일치','날짜 시차'}
    assert s['장부미대사건수']==0

def test_fee_not_exact():
    s,m,r,d=reconcile(df([('L1','2026-11-01','A',10000)]),df([('B1','2026-11-01','A',9900)]))
    assert m.iloc[0]['분류']=='수수료 추정'
    assert s['총액차이']==100

def test_split_and_unmatched():
    a=df([('L1','2026-11-01','A',300),('L2','2026-11-01','Z',50)])
    b=df([('B1','2026-11-01','A',100),('B2','2026-11-02','A',200)])
    s,m,r,d=reconcile(a,b)
    assert m.iloc[0]['분류']=='분할·합산 일치'
    assert s['장부미대사건수']==1

def test_ambiguous_not_forced():
    a=df([('L1','2026-11-01','A',100),('L2','2026-11-01','A',100)])
    b=df([('B1','2026-11-01','A',100)])
    s,m,r,d=reconcile(a,b)
    assert m.empty and s['장부미대사건수']==2
    assert len(d)==1

def test_bad_input():
    with pytest.raises(ValueError,match='중복'):
        reconcile(df([('X','2026-11-01','A',1),('X','2026-11-02','A',2)]),df([]))

def test_sign_mismatch_not_matched():
    s,m,r,d=reconcile(df([('L1','2026-11-01','A',-100)]),df([('B1','2026-11-01','A',100)]))
    assert m.empty

"""Deterministic, auditable reconciliation engine. Amounts are signed KRW integers."""
from dataclasses import dataclass
from datetime import date
from collections import defaultdict
from itertools import combinations
import pandas as pd

REQUIRED = ('거래ID', '거래일자', '거래처', '금액')

@dataclass(frozen=True)
class Config:
    date_tolerance: int = 2
    fee_tolerance: int = 1000
    group_window: int = 3
    max_group: int = 3


def normalize(df: pd.DataFrame, side: str) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f'{side}: 필수 열 누락: {", ".join(missing)}')
    x = df.copy().loc[:, list(REQUIRED)]
    if x.isna().any().any():
        raise ValueError(f'{side}: 필수 항목에 빈 값이 있습니다.')
    x['거래ID'] = x['거래ID'].astype(str).str.strip()
    x['거래처'] = x['거래처'].astype(str).str.strip()
    if (x['거래ID'] == '').any() or (x['거래처'] == '').any():
        raise ValueError(f'{side}: 거래ID/거래처가 비어 있습니다.')
    if x['거래ID'].duplicated().any():
        raise ValueError(f'{side}: 거래ID가 중복되었습니다. 각 행에 고유 ID를 부여하세요.')
    x['거래일자'] = pd.to_datetime(x['거래일자'], errors='coerce').dt.normalize()
    if x['거래일자'].isna().any():
        raise ValueError(f'{side}: 유효하지 않은 거래일자가 있습니다.')
    numbers = pd.to_numeric(x['금액'].astype(str).str.replace(',', '', regex=False), errors='coerce')
    if numbers.isna().any() or (numbers % 1 != 0).any():
        raise ValueError(f'{side}: 금액은 원 단위 정수여야 합니다.')
    x['금액'] = numbers.astype('int64')
    x['거래처키'] = x['거래처'].str.replace(r'\s+', '', regex=True).str.casefold()
    x['구분'] = side
    return x.reset_index(drop=True)


def reconcile(ledger: pd.DataFrame, bank: pd.DataFrame, cfg: Config = Config()):
    if not (0 <= cfg.date_tolerance <= 31 and 0 <= cfg.fee_tolerance <= 100000 and 1 <= cfg.group_window <= 31 and 2 <= cfg.max_group <= 4):
        raise ValueError('설정값 범위를 확인하세요.')
    l, b = normalize(ledger, '장부'), normalize(bank, '은행')
    left = l.to_dict('records'); right = b.to_dict('records')
    used_l, used_b, matches = set(), set(), []

    def days(a, z):
        return abs((a['거래일자'] - z['거래일자']).days)

    def record(li, bi, kind, note):
        for i in li: used_l.add(i)
        for j in bi: used_b.add(j)
        la = sum(left[i]['금액'] for i in li)
        ba = sum(right[j]['금액'] for j in bi)
        matches.append({'분류':kind, '장부ID':', '.join(left[i]['거래ID'] for i in li),
                        '은행ID':', '.join(right[j]['거래ID'] for j in bi),
                        '장부금액':la, '은행금액':ba, '차이(장부-은행)':la-ba,
                        '검토의견':note})

    # Unique exact matches only; ambiguous repeated amounts are deliberately left for review.
    def one_to_one(kind, predicate, note):
        while True:
            pairs = [(i,j) for i,a in enumerate(left) if i not in used_l
                     for j,z in enumerate(right) if j not in used_b and predicate(a,z)]
            dl, db = defaultdict(int), defaultdict(int)
            for i,j in pairs: dl[i]+=1; db[j]+=1
            unique = [(i,j) for i,j in pairs if dl[i]==1 and db[j]==1]
            if not unique: break
            for i,j in unique: record([i],[j],kind,note)

    one_to_one('정확 일치', lambda a,z: a['금액']==z['금액'] and a['거래일자']==z['거래일자'] and a['거래처키']==z['거래처키'], '거래처·금액·날짜 일치')
    one_to_one('날짜 시차', lambda a,z: a['금액']==z['금액'] and a['거래처키']==z['거래처키'] and 0<days(a,z)<=cfg.date_tolerance, '기표일·입출금일 차이 확인')
    one_to_one('수수료 추정', lambda a,z: a['거래처키']==z['거래처키'] and days(a,z)<=cfg.date_tolerance and 0<abs(a['금액']-z['금액'])<=cfg.fee_tolerance and (a['금액']*z['금액']>0), '수수료·공제액 추정: 증빙 확인 후 확정')

    # 1:N and N:1 subset sums, same counterparty and direction, constrained dates.
    candidates=[]
    for singles, multis, single_is_left in ((left,right,True),(right,left,False)):
        for i,a in enumerate(singles):
            if i in (used_l if single_is_left else used_b): continue
            pool=[j for j,z in enumerate(multis) if j not in (used_b if single_is_left else used_l)
                  and z['거래처키']==a['거래처키'] and z['금액']*a['금액']>0 and days(a,z)<=cfg.group_window]
            for n in range(2,min(cfg.max_group,len(pool))+1):
                for js in combinations(pool,n):
                    if sum(multis[j]['금액'] for j in js)==a['금액']:
                        li,bi=([i],list(js)) if single_is_left else (list(js),[i])
                        candidates.append((tuple(li),tuple(bi)))
    # Match only non-overlapping, unambiguous candidate groups.
    counts_l,counts_b=defaultdict(int),defaultdict(int)
    for li,bi in candidates:
        for i in li: counts_l[i]+=1
        for j in bi: counts_b[j]+=1
    for li,bi in candidates:
        if all(counts_l[i]==1 and i not in used_l for i in li) and all(counts_b[j]==1 and j not in used_b for j in bi):
            record(li,bi,'분할·합산 일치','1:N 또는 N:1 합계 일치; 거래 증빙 확인')

    # Remaining one-to-one candidate differences are *not* automatically settled.
    remaining_l=[i for i in range(len(left)) if i not in used_l]
    remaining_b=[j for j in range(len(right)) if j not in used_b]
    review=[]
    for i in remaining_l:
        a=left[i]
        related=[right[j]['거래ID'] for j in remaining_b if right[j]['거래처키']==a['거래처키'] and days(a,right[j])<=cfg.group_window]
        review.append({'구분':'장부 미대사','거래ID':a['거래ID'],'거래일자':a['거래일자'].date().isoformat(),
                       '거래처':a['거래처'],'금액':a['금액'],'관련 후보ID':', '.join(related),
                       '검토의견':'관련 거래 금액·증빙 확인' if related else '은행 반영 누락·미결제 여부 확인'})
    for j in remaining_b:
        z=right[j]
        related=[left[i]['거래ID'] for i in remaining_l if left[i]['거래처키']==z['거래처키'] and days(z,left[i])<=cfg.group_window]
        review.append({'구분':'은행 미대사','거래ID':z['거래ID'],'거래일자':z['거래일자'].date().isoformat(),
                       '거래처':z['거래처'],'금액':z['금액'],'관련 후보ID':', '.join(related),
                       '검토의견':'관련 장부 금액·증빙 확인' if related else '장부 기표 누락 여부 확인'})
    # Duplicate candidates are flags, never automatically deleted.
    duplicates=[]
    for side,df in (('장부',l),('은행',b)):
        for _,g in df.groupby(['거래일자','거래처키','금액']):
            if len(g)>1:
                duplicates.append({'구분':side,'거래ID':', '.join(g['거래ID']), '건수':len(g),
                                   '금액':int(g['금액'].iloc[0]),'검토의견':'동일 날짜·거래처·금액 반복: 중복 여부 확인'})
    m=pd.DataFrame(matches,columns=['분류','장부ID','은행ID','장부금액','은행금액','차이(장부-은행)','검토의견'])
    r=pd.DataFrame(review,columns=['구분','거래ID','거래일자','거래처','금액','관련 후보ID','검토의견'])
    d=pd.DataFrame(duplicates,columns=['구분','거래ID','건수','금액','검토의견'])
    summary={'장부건수':len(l),'은행건수':len(b),'대사그룹':len(m),'장부매칭건수':len(used_l),
             '은행매칭건수':len(used_b),'장부미대사건수':len(remaining_l),'은행미대사건수':len(remaining_b),
             '장부미대사금액':sum(left[i]['금액'] for i in remaining_l),
             '은행미대사금액':sum(right[j]['금액'] for j in remaining_b),
             '장부총액':int(l['금액'].sum()),'은행총액':int(b['금액'].sum()),
             '총액차이':int(l['금액'].sum()-b['금액'].sum()),
             '장부매칭률':round(100*len(used_l)/len(l),1) if len(l) else 100.0}
    return summary,m,r,d

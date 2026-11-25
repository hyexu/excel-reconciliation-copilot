import io
import pandas as pd
import streamlit as st
from reconciliation import reconcile, Config

st.set_page_config(page_title='Excel Reconciliation Copilot',page_icon='📊',layout='wide')
st.title('Excel Reconciliation Copilot')
st.caption('장부 ↔ 은행 거래 자동 대사 | 규칙 기반, 추적 가능한 검토 결과')
st.info('시연용 도구입니다. 자동 매칭은 회계적 확정이 아니며 수수료·분할거래·미대사 항목은 증빙 확인이 필요합니다.')
with st.sidebar:
    st.header('대사 규칙')
    date_tol=st.slider('날짜 허용 오차(일)',0,10,2)
    fee_tol=st.number_input('수수료 추정 최대 차이(원)',min_value=0,max_value=100000,value=1000,step=100)
    group_window=st.slider('분할·합산 날짜 범위(일)',1,14,3)
    max_group=st.slider('합산 최대 거래 건수',2,4,3)
    st.caption('거래처는 공백·대소문자만 정규화합니다. 동일 거래처의 다른 표기는 사전 정리가 필요합니다.')
c1,c2=st.columns(2)
with c1: f1=st.file_uploader('① 장부 엑셀',type=['xlsx'],key='ledger')
with c2: f2=st.file_uploader('② 은행 엑셀',type=['xlsx'],key='bank')
st.caption('필수 열: 거래ID / 거래일자 / 거래처 / 금액. 입금(+)·출금(-) 부호를 두 파일에서 통일하세요.')
if f1 and f2:
    try:
        a=pd.read_excel(f1,engine='openpyxl'); b=pd.read_excel(f2,engine='openpyxl')
        s,m,r,d=reconcile(a,b,Config(date_tol,int(fee_tol),group_window,max_group))
        cols=st.columns(4)
        cols[0].metric('장부 매칭률',f"{s['장부매칭률']}%")
        cols[1].metric('장부 미대사',f"{s['장부미대사건수']}건")
        cols[2].metric('은행 미대사',f"{s['은행미대사건수']}건")
        cols[3].metric('전체 금액 차이',f"{s['총액차이']:,}원")
        st.warning('총액 차이 = 장부총액 − 은행총액. 매칭된 수수료 추정 차이도 총액 차이에 포함됩니다.')
        t1,t2,t3,t4=st.tabs(['대사 결과','미대사·검토','중복 의심','집계·내보내기'])
        with t1: st.dataframe(m,use_container_width=True,hide_index=True)
        with t2: st.dataframe(r,use_container_width=True,hide_index=True)
        with t3: st.dataframe(d,use_container_width=True,hide_index=True)
        with t4:
            st.dataframe(pd.DataFrame([s]),use_container_width=True,hide_index=True)
            st.write('매칭 유형별 건수')
            st.dataframe(m['분류'].value_counts().rename_axis('분류').reset_index(name='건수'),hide_index=True)
        output=io.BytesIO()
        with pd.ExcelWriter(output,engine='openpyxl') as writer:
            pd.DataFrame([s]).to_excel(writer,sheet_name='요약',index=False)
            m.to_excel(writer,sheet_name='대사결과',index=False)
            r.to_excel(writer,sheet_name='미대사',index=False)
            d.to_excel(writer,sheet_name='중복의심',index=False)
        st.download_button('📥 대사 결과 엑셀 다운로드',output.getvalue(),file_name='reconciliation_result.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        st.error(f'파일을 처리할 수 없습니다: {e}')
else:
    st.markdown('**시작하기:** `samples/` 폴더의 장부·은행 예제 파일을 업로드하세요.')

"""Exercise the generic template with synthetic data in a temporary directory.
Usage: python check_browser.py --chrome /path/to/chrome
Requires websocket-client plus report dependencies. Does not call an engine or scheduler.
"""
import argparse,json,subprocess,tempfile,time,urllib.request
from pathlib import Path
import websocket
from test_package import report_fixture
from render_report import render

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--chrome',required=True);args=ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);html=render(report_fixture(root/'inputs'),root/'report');profile=root/'profile'
        proc=subprocess.Popen([args.chrome,'--headless','--no-sandbox','--disable-gpu','--renderer-process-limit=2','--num-raster-threads=1','--remote-debugging-port=0','--user-data-dir='+str(profile),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.time()+30
            while not (profile/'DevToolsActivePort').exists():
                if time.time()>deadline:raise TimeoutError('Browser startup')
                time.sleep(.1)
            port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
            pages=json.load(urllib.request.urlopen('http://127.0.0.1:'+port+'/json'))
            ws=websocket.create_connection(pages[0]['webSocketDebuggerUrl'],suppress_origin=True,timeout=20);seq=0;errors=[]
            def call(method,params=None):
                nonlocal seq
                seq+=1;ws.send(json.dumps(dict(id=seq,method=method,params=params or {})))
                while True:
                    msg=json.loads(ws.recv())
                    if msg.get('method')=='Runtime.exceptionThrown':errors.append(msg['params'])
                    if msg.get('id')==seq:
                        if 'error' in msg:raise RuntimeError(msg['error'])
                        return msg.get('result',{})
            def js(expr):
                value=call('Runtime.evaluate',dict(expression=expr,returnByValue=True,awaitPromise=True))
                if 'exceptionDetails' in value:raise RuntimeError(value['exceptionDetails'])
                return value['result'].get('value')
            def change(name,value):
                js('document.getElementById('+json.dumps(name)+').value='+json.dumps(value)+';document.getElementById('+json.dumps(name)+').dispatchEvent(new Event("change"));true')
                js('new Promise(r=>setTimeout(()=>r(true),200))')
            call('Runtime.enable');call('Page.enable');call('Page.navigate',dict(url=html.as_uri()))
            deadline=time.time()+30
            while not js('Boolean(window.reportReady)'):
                if time.time()>deadline:raise TimeoutError('Report initialization: '+str(errors))
                time.sleep(.2)
            assert js('document.querySelectorAll(".js-plotly-plot").length')==5
            change('parameterSection','kinetics');change('cutoff_adaptation','1')
            assert 'adaptation: 1 candidates' in js('document.getElementById("parameterCounts").textContent')
            change('cutoff_adaptation','5')
            assert 'adaptation: 2 candidates' in js('document.getElementById("parameterCounts").textContent')
            assert js('document.getElementById("imageStage")===null')
            assert js('document.querySelectorAll("#imageGrid img").length')==5
            assert js('document.querySelector("#growthMetric option[value=area_quantiles]").disabled')
            js('new Promise(r=>setTimeout(()=>r(true),300))')
            assert js('Promise.all(Array.from(document.querySelectorAll("#imageGrid img")).map(i=>{i.loading="eager";return i.decode().then(()=>i.naturalWidth===80);})).then(a=>a.every(Boolean))')
            change('component','Morphology');change('countScale','log');change('parameterScope','new');change('rank','2')
            change('group','lineage-beta')
            assert 'No scored candidate' in js('document.getElementById("summaryTable").textContent')
            change('group','lineage-alpha');change('rank','1')
            assert js('document.querySelectorAll("#imageGrid img").length')==5
            # Add generic phenotypes and >20 passages; exercise new views and stacked timepoints.
            js("""(()=>{
              const g=D.growth[0],v={coverage:[.2,.4],gap:[8,4],clark_evans:[1,1.1],area_quantiles:[[.3,.6,1,1.4,2],[.4,.7,1,1.3,1.8]]};
              g.metrics={observed:v,simulations:Object.fromEntries(D.models.map(m=>[m,v]))};
              for(let i=1;i<21;i++)D.growth.push({...g,episode:'example-'+i,passage:i+1});
              D.fields.push({...D.fields[0],id:'second-time',time:2,passage_id:'acq-b'});
              all();return true;
            })()""")
            assert js('document.querySelectorAll(".field-timepoint").length')==2
            assert js('document.querySelectorAll("#imageGrid img").length')==10
            assert js('document.getElementById("growthPlot").layout.annotations.length')==20
            assert js('document.getElementById("growthPlot").layout.grid.columns')==5
            assert js('document.getElementById("growthPlot").layout.grid.rows')==4
            change('growthPage','1')
            assert js('document.getElementById("growthPlot").layout.annotations.length')==1
            for metric in ['area_quantiles','coverage','gap','clark_evans']:
                change('growthMetric',metric)
                assert js('document.getElementById("growthPlot").data.length')>0
                if metric=='area_quantiles':
                    assert js('document.getElementById("growthPlot").data.some(t=>t.fill==="tonexty")')
                    assert js('document.getElementById("growthPlot").data.some(t=>t.type==="box")')
            for plot in ['componentScatter','parityPlot']:
                assert js('Array.from(document.querySelectorAll("#'+plot+' .xtitle,#'+plot+' .ytitle")).filter(e=>e.textContent&&!e.textContent.includes("Click to enter")).length')==2
            change('group','lineage-beta')
            assert js('document.getElementById("growthMetric").value')=='count'
            assert not errors,errors
            ws.close();print('Portable browser checks passed: arbitrary groups, custom components, missing stage, cutoffs, images and controls.')
        finally:
            proc.terminate();proc.wait(timeout=15)
if __name__=='__main__':main()

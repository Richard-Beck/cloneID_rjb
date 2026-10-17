"""Bounded diagnostic traces; optimization sees the identical objectives/moves."""
from pathlib import Path
import hashlib
import json

class Trace:
    def __init__(self,path,limit=524288):
        self.path=Path(path);self.limit=limit;self.stream=self.path.open('w');self.bytes=0;self.records=0;self.retained=0;self.digest=hashlib.sha256()
    def write(self,value):
        data=value.encode();self.records+=1;self.digest.update(data)
        if self.bytes+len(data)<=self.limit:self.stream.write(value);self.stream.flush();self.bytes+=len(data);self.retained+=1
        return len(value)
    def close(self):
        self.stream.close();self.path.with_suffix(self.path.suffix+'.summary.json').write_text(json.dumps({'records_seen':self.records,'records_retained':self.retained,'records_omitted':self.records-self.retained,'byte_limit':self.limit,'bytes_retained':self.bytes,'all_records_stream_sha256':self.digest.hexdigest(),'omission_affects_diagnostic_trace_only':True},indent=2)+'\n')

class Records(list):
    def __init__(self,limit=524288):super().__init__();self.limit=limit;self.bytes=0;self.records=0;self.digest=hashlib.sha256()
    def append(self,value):
        data=(json.dumps(value,sort_keys=True)+'\n').encode();self.records+=1;self.digest.update(data)
        if self.bytes+len(data)<=self.limit:self.bytes+=len(data);super().append(value)
    def summary(self):return {'records_seen':self.records,'records_retained':len(self),'records_omitted':self.records-len(self),'bytes_retained':self.bytes,'byte_limit':self.limit,'all_records_stream_sha256':self.digest.hexdigest(),'omission_affects_diagnostic_trace_only':True}

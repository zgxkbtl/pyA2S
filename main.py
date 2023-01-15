import contextlib
from subprocess import call
from fastapi import FastAPI, Request, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from asyncio import Event
import asyncio
from uuid import uuid4
import json
import httpx

class A2SRecord(BaseModel):
    requestID: str = None
    echoProxy: bool
    randomCallBack: bool
    proxyAddr: str
    callBackAddr: str
    expire: int = None

class A2SCallback(BaseModel):
    callbackID: str = None

app = FastAPI()

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# key variables
callback_event = {} # callback event(signals) of async 
records_dict = {} # quick search record
ret_msg = {} # callback Request
CALL_BACK_URL_PREFIX = 'https://alley.luobotou.org:8000/a2s/callback/'


@app.on_event("startup")
async def startup_event():
    # app.state['']
    pass

@app.get("/")
async def root():
    # items['e'].set()
    return {"message": uuid4()}

@app.post('/a2s/request/{req_id}')
async def request_a2s(req_id:str, req: Request):

    callback_id = str(uuid4())

    async def build_body(rec: A2SRecord):
        req_body = await req.body()
        req_body = req_body.decode()
        req_json = json.loads(req_body)
        req_json['A2S'] = {
            'callback': CALL_BACK_URL_PREFIX + callback_id,
            'callbackId': callback_id
        }
        return req_json

    class CallbackEventContext:

        def __init__(self, callback_id) -> Event:
            self.callback_id = callback_id

        def __enter__(self) -> Event:
            callback_event[self.callback_id] = Event()
            return callback_event[self.callback_id]

        def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
            del callback_event[self.callback_id]
            if exc_type:
                print(exc_val)
            return True

    if req_id in records_dict and records_dict[req_id].proxyAddr:
        rec: A2SRecord = records_dict[req_id]
        req_json = await build_body(rec)
        is_set = False
        with CallbackEventContext(callback_id) as event:
            res = httpx.post(rec.proxyAddr, json=req_json)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(event.wait(), rec.expire)
            is_set = event.is_set()

        if not is_set:
            raise HTTPException(status_code=504, detail="wait callback timeout")

        callback_request:Request = ret_msg[callback_id]
        try:
            cb_json = json.loads( await callback_request.body())
        except json.decoder.JSONDecodeError as e:
            print(e.msg)
            raise HTTPException(status_code=500, detail="json decode faild")
        except Exception as e:
            print(e.with_traceback())
            raise HTTPException(status_code=500, detail="cb_json create faild")
        finally:
            del ret_msg[callback_id]
        return cb_json
    elif req_id in records_dict:
        return await req.body()

    else:
        raise HTTPException(status_code=404, detail="No match for request id" + req_id)


@app.post('/a2s/callback/{callback_id}')
async def request_a2s(callback_id:str, req: Request):
    print(callback_id)
    if callback_id in callback_event:
        cbid = callback_id
        ret_msg[cbid] = req
        callback_event[cbid].set()
        del callback_event[cbid]
        return await req.body()
    else:
        raise HTTPException(status_code=404, detail="Callback ID not found")


@app.post("/a2s/create")
async def create_a2s(record: A2SRecord):
    rid = str(uuid4())
    record.requestID = rid
    if not record.expire: record.expire = 600
    records_dict[rid] = record
    return record

@app.get("/a2s/list")
async def list_a2s():
    return list(records_dict.values())


@app.get("/a2s/delete/")
async def delete_a2s(req_id: str):
    if req_id in records_dict:
        del records_dict[req_id]
    return {"success": True}

@app.get("/a2s/listwaiting/")
async def list_wating_event():
    return list(callback_event.keys())

"""
using tmux
uvicorn main:app --host 0.0.0.0 --ssl-keyfile /root/a2s/7276018__luobotou.org.key --ssl-certfile /root/a2s/7276018__luobotou.org.pem --reload
"""
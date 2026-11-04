//+------------------------------------------------------------------+
//| SIW_Webhook.mq5 — SIW v2 (Star-in-Wick) XAUUSD M5, exit v4        |
//| SKETCH, NOT COMPILED/TESTED. Watch-only: NEVER places orders.     |
//| On each new closed M5 bar: compute SIW on bar 1 (= confirm bar L) |
//| and POST JSON to WebhookURL (n8n webhook / CF Worker / ntfy).     |
//| MT5: Tools > Options > Expert Advisors > "Allow WebRequest for    |
//| listed URL" and add the webhook host (e.g. https://ntfy.sh).      |
//+------------------------------------------------------------------+
#property strict
input string WebhookURL   = "https://ntfy.sh/your-topic"; // or n8n/Worker URL
input bool   PostHeartbeat= false;  // also POST every bar (bars online)
input double StarBodyMax=0.40, PinWickMin=0.50, PinBodyMax=0.35, WickTol=0.30, EngulfTol=0.10, MaxExt=10.0;
input int    LegLookback=12, DedupeBars=3;
input double V4SL=10.0, V4TP=20.0; input int V4Bars=2;   // exit v4: SL $10, TP $20 cap, close at close of L+2 (10 min)
int hE21, hE55; datetime lastBar=0, lastSig[2]={0,0};

int OnInit(){ hE21=iMA(_Symbol,PERIOD_M5,21,0,MODE_EMA,PRICE_CLOSE); hE55=iMA(_Symbol,PERIOD_M5,55,0,MODE_EMA,PRICE_CLOSE);
  return (hE21==INVALID_HANDLE||hE55==INVALID_HANDLE)?INIT_FAILED:INIT_SUCCEEDED; }

double O(int s){return iOpen(_Symbol,PERIOD_M5,s);} double H(int s){return iHigh(_Symbol,PERIOD_M5,s);}
double L_(int s){return iLow(_Symbol,PERIOD_M5,s);} double C(int s){return iClose(_Symbol,PERIOD_M5,s);}

// returns "PIN"/"STAR"/"" for bar s vs previous bar s+1, direction sell=true
string Rej(int s,bool sell){
  double rng=MathMax(H(s)-L_(s),1e-9), top=MathMax(O(s),C(s)), bot=MathMin(O(s),C(s)), bp=MathAbs(C(s)-O(s))/rng;
  double uw=(H(s)-top)/rng, lw=(bot-L_(s))/rng, ptop=MathMax(O(s+1),C(s+1)), pbot=MathMin(O(s+1),C(s+1));
  if(sell){ if(uw>=PinWickMin && bp<=PinBodyMax) return "PIN";
            if(bp<=StarBodyMax && bot>=ptop-WickTol && top<=H(s+1)+WickTol && H(s+1)>ptop) return "STAR"; }
  else    { if(lw>=PinWickMin && bp<=PinBodyMax) return "PIN";
            if(bp<=StarBodyMax && top<=pbot+WickTol && bot>=L_(s+1)-WickTol && pbot>L_(s+1)) return "STAR"; }
  return "";
}
bool Engulf(int s,bool sell){
  if(sell) return C(s)<O(s) && C(s+1)>O(s+1) && O(s)>=C(s+1)-EngulfTol && C(s)<=O(s+1)+EngulfTol;
  return C(s)>O(s) && C(s+1)<O(s+1) && O(s)<=C(s+1)+EngulfTol && C(s)>=O(s+1)-EngulfTol;
}
string Classify(int s,bool sell){
  string k=Rej(s,sell); if(k!="") return "A_"+k;
  if(Engulf(s,sell)) return "B_ENGULF";
  bool colour= sell ? C(s)<O(s) : C(s)>O(s);
  if(colour){ k=Rej(s+1,sell); if(k!="") return "C_"+k; }
  return "";
}
void Post(string json){
  char data[],res[]; string hdr="Content-Type: application/json\r\n",rh;
  StringToCharArray(json,data,0,StringLen(json),CP_UTF8);
  int code=WebRequest("POST",WebhookURL,hdr,5000,data,res,rh);
  if(code<0) Print("WebRequest error ",GetLastError()," — add URL to allowed list"); else Print("POST ",code);
}
void OnTick(){
  datetime t0=iTime(_Symbol,PERIOD_M5,0); if(t0==lastBar) return; lastBar=t0;   // new bar opened => bar 1 just closed
  double e21[1],e55[1]; if(CopyBuffer(hE21,0,1,1,e21)<1||CopyBuffer(hE55,0,1,1,e55)<1) return;
  bool sell = e21[0]<e55[0]; string k=Classify(1,sell);
  string bar=StringFormat("\"bar\":{\"t\":%d,\"o\":%.2f,\"h\":%.2f,\"l\":%.2f,\"c\":%.2f,\"e21\":%.3f,\"e55\":%.3f}",
             (long)iTime(_Symbol,PERIOD_M5,1),O(1),H(1),L_(1),C(1),e21[0],e55[0]);
  if(k!=""){
    double ext=0; if(sell){ double hh=H(1); for(int i=1;i<=LegLookback;i++) hh=MathMax(hh,H(i)); ext=hh-C(1);} 
                  else    { double ll=L_(1); for(int i=1;i<=LegLookback;i++) ll=MathMin(ll,L_(i)); ext=C(1)-ll;}
    int d=sell?0:1; datetime tL=iTime(_Symbol,PERIOD_M5,1);
    if(ext<=MaxExt && (tL-lastSig[d])>=DedupeBars*PeriodSeconds(PERIOD_M5)){
      lastSig[d]=tL; double e=O(0), sg=sell?-1:1;
      datetime texit=t0+V4Bars*PeriodSeconds(PERIOD_M5);   // close of L+2 (server time)
      Post(StringFormat("{\"type\":\"signal\",\"symbol\":\"%s\",\"dir\":\"%s\",\"kind\":\"%s\",\"entry\":%.2f,\"sl\":%.2f,\"tp\":%.2f,\"exit_srv\":\"%s\",\"leg_ext\":%.2f,%s}",
           _Symbol,sell?"S":"B",k,e,e-sg*V4SL,e+sg*V4TP,TimeToString(texit,TIME_MINUTES),ext,bar));
      return;
    }
  }
  if(PostHeartbeat) Post(StringFormat("{\"type\":\"bar\",\"symbol\":\"%s\",%s}",_Symbol,bar));
}

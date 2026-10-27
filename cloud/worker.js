// Cloudflare Worker: always-on Telegram webhook + D1 catalog, no personal PC.
const json = (obj, status=200) => new Response(JSON.stringify(obj), {
  status, headers: {"content-type":"application/json; charset=utf-8"}
});
const h = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const ms = () => Math.floor(Date.now()/1000);
const stringEq = (a,b) => typeof a==="string" && typeof b==="string" && a.length>0 && a===b;
const allowed = (env, userId) => String(env.ALLOWED_USER_IDS ?? "").split(",").map(s=>s.trim()).filter(Boolean).includes(String(userId));

async function notify(env, chatId, message) {
  // No Markdown injection: all dynamic fields are escaped, only static HTML tags used.
  const res = await fetch("https://api.telegram.org/bot"+env.BOT_TOKEN+"/sendMessage", {
    method:"POST", headers:{"content-type":"application/json"},
    body:JSON.stringify({chat_id:chatId,text:message.slice(0,3900),parse_mode:"HTML",disable_web_page_preview:true})
  });
  if (!res.ok) throw new Error("Telegram sendMessage returned "+res.status);
}
function normalizedRow(r, env) {
  const value=Number(r.price);
  let converted=null;
  if(r.currency==="VND") converted=value;
  if(r.currency==="USD" && Number(env.FX_USD_VND)>0) converted=value*Number(env.FX_USD_VND);
  if(r.currency==="USDT" && Number(env.FX_USDT_VND)>0) converted=value*Number(env.FX_USDT_VND);
  // Refuse to compare different currencies unless all are explicitly convertible.
  return {...r, converted};
}
function formatPrice(p,c) {
  return Number(p).toLocaleString("en-US",{maximumFractionDigits:c==="VND"?0:3})+" "+h(c);
}
function groupRows(rows, env) {
  const groups=new Map();
  for(const original of rows) {
    if(!original.in_stock) continue;
    const r=normalizedRow(original,env);
    const unit=r.converted===null?r.currency:"VND";
    const amount=r.converted===null?Number(r.price):r.converted;
    const key=[r.canonical_name,r.spec_key,unit].join("\u001f");
    if(!groups.has(key)) groups.set(key,{name:r.canonical_name,spec:r.spec_key,unit,offers:[]});
    groups.get(key).offers.push({...r,amount});
  }
  return [...groups.values()].map(g=>({...g,offers:g.offers.sort((a,b)=>a.amount-b.amount)}))
    .sort((a,b)=>a.name.localeCompare(b.name)||a.spec.localeCompare(b.spec));
}
async function lookup(env, command, term) {
  const cutoff=ms()-Math.max(1,Number(env.MAX_AGE_HOURS||24))*3600;
  let query="SELECT * FROM offers WHERE last_seen >= ?";
  const binds=[cutoff];
  if(term){
    query+=" AND (lower(canonical_name) LIKE ? OR lower(raw_name) LIKE ?)";
    const key="%"+term.toLowerCase().slice(0,80)+"%";
    binds.push(key,key);
  }
  query+=" ORDER BY canonical_name LIMIT 500";
  const rows=(await env.DB.prepare(query).bind(...binds).all()).results||[];
  const groups=groupRows(rows,env);
  if(!groups.length) return "Không có báo giá còn hàng và mới trong "+h(env.MAX_AGE_HOURS||24)+" giờ qua.";
  const max=command==="/top"?5:command==="/compare"?8:10;
  const chosen=command==="/top"
    ? groups.sort((a,b)=>a.offers[0].amount-b.offers[0].amount).slice(0,max)
    : groups.slice(0,max);
  const lines=["<b>TelePriceHub — bảng giá đã kiểm tra</b>"];
  for(const g of chosen) {
    const best=g.offers[0];
    lines.push("\n<b>"+h(g.name)+"</b> · "+h(g.spec));
    lines.push("Rẻ nhất: <b>"+formatPrice(best.amount,g.unit)+"</b> — "+h(best.supplier));
    if(command==="/compare"){
      for(const o of g.offers.slice(0,8)) {
        const pct=best.amount>0?Math.round((o.amount/best.amount-1)*1000)/10:0;
        lines.push(" • "+h(o.supplier)+": "+formatPrice(o.price,o.currency)+
          (o.converted!==null && o.currency!=="VND"?" (≈ "+formatPrice(o.amount,"VND")+")":"")+
          " (+"+pct+"%)");
      }
    }
  }
  lines.push("\n<i>Chỉ tính hàng còn, giá mới trong "+h(env.MAX_AGE_HOURS||24)+" giờ. Không quy đổi ngoại tệ nếu chưa đặt tỷ giá.</i>");
  return lines.join("\n");
}

async function handleTelegram(req,env) {
  if(!stringEq(req.headers.get("X-Telegram-Bot-Api-Secret-Token"),env.TELEGRAM_WEBHOOK_SECRET)) return json({ok:false},403);
  const update=await req.json();
  const msg=update?.message;
  if(!msg || typeof msg.text!=="string") return json({ok:true});
  if(msg.chat?.type!=="private" || !allowed(env,msg.from?.id)) return json({ok:true});
  const input=msg.text.trim();
  const command=input.split(/\s+/)[0].split("@")[0].toLowerCase();
  const term=input.slice(input.indexOf(" ")+1).trim();
  let response;
  if(command==="/start" || command==="/help") response="<b>TelePriceHub</b>\n/search tên — tìm giá\n/compare tên — so sánh\n/top — giá thấp nhất\n/status — tình trạng đồng bộ";
  else if(command==="/status") {
    const cutoff=ms()-Number(env.MAX_AGE_HOURS||24)*3600;
    const stat=await env.DB.prepare("SELECT COUNT(*) cnt,COUNT(DISTINCT supplier) suppliers,MAX(last_seen) latest FROM offers WHERE last_seen >= ?").bind(cutoff).first();
    response="Sản phẩm/báo giá còn mới: "+(stat?.cnt||0)+"\nNhà cung cấp: "+(stat?.suppliers||0)+"\nCập nhật gần nhất: "+(stat?.latest?new Date(stat.latest*1000).toISOString():"Chưa có");
  }
  else if(["/search","/compare","/top"].includes(command)){
    if(command!=="/top" && (!input.includes(" ") || !term)) response="Cách dùng: "+h(command)+" netflix";
    else response=await lookup(env,command,command==="/top"?"":term);
  } else response="Dùng /help để xem các lệnh.";
  await notify(env,msg.chat.id,response);
  return json({ok:true});
}
async function handleIngest(req,env) {
  const token=req.headers.get("Authorization")||"";
  if(!stringEq(token,"Bearer "+env.SYNC_TOKEN) || !env.SYNC_TOKEN) return json({error:"unauthorized"},401);
  const data=await req.json();
  if(!Array.isArray(data.offers) || data.offers.length>80) return json({error:"offers must be an array of at most 80"},400);
  const now=ms(); const statements=[];
  for(const item of data.offers) {
    if(!item.supplier || !item.canonical_name || !item.spec_key || !["VND","USD","USDT"].includes(item.currency) ||
       !(Number(item.price)>0) || String(item.supplier).length>128 || String(item.canonical_name).length>200)
      return json({error:"invalid offer"},400);
    const values=[item.supplier,item.canonical_name,item.spec_key,item.currency];
    const old=await env.DB.prepare("SELECT price, in_stock FROM offers WHERE supplier=? AND canonical_name=? AND spec_key=? AND currency=?").bind(...values).first();
    const stock=item.in_stock?1:0;
    if(!old || Number(old.price)!==Number(item.price) || Number(old.in_stock)!==stock) {
      statements.push(env.DB.prepare("INSERT INTO price_history(supplier,canonical_name,spec_key,price,currency,in_stock,changed_at) VALUES(?,?,?,?,?,?,?)")
        .bind(item.supplier,item.canonical_name,item.spec_key,Number(item.price),item.currency,stock,now));
    }
    statements.push(env.DB.prepare("INSERT INTO offers(supplier,canonical_name,spec_key,raw_name,price,currency,in_stock,last_seen) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(supplier,canonical_name,spec_key,currency) DO UPDATE SET raw_name=excluded.raw_name,price=excluded.price,in_stock=excluded.in_stock,last_seen=excluded.last_seen")
      .bind(item.supplier,item.canonical_name,item.spec_key,String(item.raw_name||"").slice(0,200),Number(item.price),item.currency,stock,now));
  }
  if(statements.length) await env.DB.batch(statements);
  return json({ok:true,count:data.offers.length});
}
export default {
  async fetch(request,env) {
    try {
      const {pathname}=new URL(request.url);
      if(pathname==="/health" && request.method==="GET") return json({ok:true,service:"TelePriceHub"});
      if(pathname==="/telegram" && request.method==="POST") return await handleTelegram(request,env);
      if(pathname==="/ingest" && request.method==="POST") return await handleIngest(request,env);
      return json({error:"not found"},404);
    } catch (err) {
      console.error("Worker error",String(err));
      return json({error:"internal error"},500);
    }
  }
};

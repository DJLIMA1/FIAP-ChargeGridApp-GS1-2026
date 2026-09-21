"""Same-origin landing page for Supabase confirmation and password-recovery links."""

AUTH_PAGE = """<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><meta name="color-scheme" content="light dark">
<title>ChargeGrid — sua conta</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#202124;background:#f2f3f5;color-scheme:light}
*{box-sizing:border-box}body{margin:0;min-height:100dvh;display:grid;place-items:center;padding:24px}
main{width:100%;max-width:420px}header{font-weight:800;font-size:25px;margin-bottom:36px}
header span{color:#dc262e}h1{font-size:28px;letter-spacing:-.6px;margin:0 0 12px}
p{line-height:1.6;color:#626975}label{display:block;margin:22px 0 8px;font-size:14px}
input,button{width:100%;font:inherit;border-radius:8px;padding:13px 15px}
input{border:1px solid #d1d5db;background:white;color:inherit}input:focus{outline:2px solid #dc262e}
button{margin-top:24px;background:#dc262e;color:white;border:0;font-weight:650;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}.message{min-height:24px;font-size:14px}
.error{color:#b91c1c}.foot{font-size:13px;margin-top:28px}[hidden]{display:none!important}
@media(prefers-color-scheme:dark){:root{color:#f5f6f8;background:#11151d;color-scheme:dark}
p{color:#aeb7c5}input{background:#1c2430;border-color:#3a4657}.error{color:#ff9494}}
</style></head>
<body><main><header><span>⚡</span> ChargeGrid</header>
<h1>Confirmação de e-mail</h1>
<p id="detail">Abra o link recebido por e-mail para confirmar sua conta ou redefinir sua senha.</p>
<form id="recovery" hidden>
<label for="password">Nova senha</label>
<input id="password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required>
<label for="confirm">Confirme a nova senha</label>
<input id="confirm" type="password" autocomplete="new-password" minlength="8" maxlength="128" required>
<button type="submit">Salvar nova senha</button>
<p id="message" class="message" role="status" aria-live="polite"></p>
</form><p class="foot">Depois de concluir, volte ao aplicativo ChargeGrid.</p></main>
<script>
(()=>{
const query=new URLSearchParams(location.search),hash=new URLSearchParams(location.hash.slice(1));
let token=hash.get('access_token');
const type=hash.get('type'),error=query.get('error_code')||hash.get('error_code')||hash.get('error');
history.replaceState(null,'',location.pathname);
const title=document.querySelector('h1'),detail=document.querySelector('#detail');
const form=document.querySelector('#recovery'),message=document.querySelector('#message');
if(error){token=null;title.textContent='Link inválido ou expirado';
detail.textContent='Solicite uma nova mensagem no aplicativo ChargeGrid e abra o link mais recente.';}
else if(type==='recovery'&&token){title.textContent='Crie uma nova senha';
detail.textContent='Use pelo menos 8 caracteres. Evite senhas fáceis de adivinhar.';form.hidden=false;}
else if(type==='signup'&&token){token=null;title.textContent='E-mail confirmado';
detail.textContent='Sua conta está pronta. Volte ao aplicativo e entre com sua senha.';}
else{token=null;}
form.addEventListener('submit',async(event)=>{
event.preventDefault();message.className='message error';
const password=document.querySelector('#password').value;
if(password!==document.querySelector('#confirm').value){message.textContent='As senhas não coincidem.';return;}
if(password.length<8){message.textContent='Use pelo menos 8 caracteres.';return;}
const button=form.querySelector('button');button.disabled=true;button.textContent='Salvando…';
message.textContent='';const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),20000);
try{
const response=await fetch('/v1/auth/password/update',{method:'POST',
headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
body:JSON.stringify({password}),signal:controller.signal,cache:'no-store'});
const result=await response.json();
if(!response.ok){message.textContent=response.status===401?'Link expirado. Solicite um novo link no aplicativo.':
(result.error?.message||'Não foi possível alterar a senha. Tente novamente.');return;}
token=null;form.reset();form.hidden=true;title.textContent='Senha alterada';
detail.textContent='Tudo pronto. Volte ao aplicativo ChargeGrid e entre com a nova senha.';
}catch{message.textContent='Não foi possível conectar. Verifique sua internet e tente novamente.';}
finally{clearTimeout(timeout);button.disabled=false;button.textContent='Salvar nova senha';}
});
})();
</script></body></html>"""

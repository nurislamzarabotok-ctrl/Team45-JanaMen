'use strict';
// No credentials, HR records or user messages are put in Cache Storage.
(()=>{
 const root=document.documentElement;
 let previousFocus=null,waitingWorker=null,reloadRequested=false;
 const mobile=()=>matchMedia('(max-width:760px)').matches;
 function viewport(){
  const v=window.visualViewport;
  root.style.setProperty('--visual-height',`${Math.round(v?.height||innerHeight)}px`);
  root.style.setProperty('--visual-top',`${Math.round(v?.offsetTop||0)}px`);
  const typing=document.activeElement?.matches('input,textarea,select');
  root.classList.toggle('keyboard-open',mobile()&&!!typing&&!!v&&innerHeight-v.height>120);
 }
 function setMenu(open){
  const panel=$('.sidebar');if(!panel)return;
  if(open)previousFocus=document.activeElement;
  root.classList.toggle('mobile-menu-open',open);
  panel.classList.toggle('open',open);panel.setAttribute('aria-hidden',String(!open));panel.inert=!open;
  panel.setAttribute('role','dialog');panel.setAttribute('aria-modal',String(open));
  $('.mobile-shade')?.classList.toggle('open',open);
  $$('.menu-btn,.mobile-tabs [data-action=menu]').forEach(b=>b.setAttribute('aria-expanded',String(open)));
  for(const node of [$('#content'),$('.site-footer'),$('.mobile-tabs')])if(node)node.inert=open;
  if(open){panel.scrollTop=0;$('.drawer-head button',panel)?.focus({preventScroll:true});}
  else if(previousFocus?.isConnected){previousFocus.focus({preventScroll:true});previousFocus=null;}
 }
 function tabs(){
  if(!state.user)return;
  $('.mobile-tabs')?.remove();$('.mobile-sync')?.remove();
  const nav=document.createElement('nav');nav.className='mobile-tabs';nav.setAttribute('aria-label','Быстрые разделы');
  nav.innerHTML=[['home','home','Обзор'],['workspace','users','Задачи'],['assistant','spark','Jana AI']].map(([p,i,t])=>`<button data-page="${p}" class="${state.page===p?'active':''}" ${state.page===p?'aria-current="page"':''}>${icon(i)}<span>${t}</span></button>`).join('')+`<button data-action="menu" aria-label="Все разделы" aria-expanded="false">${icon('menu')}<span>Меню</span></button>`;
  $('.layout')?.append(nav);
  const line=document.createElement('div');line.className='mobile-sync';line.setAttribute('role','status');line.innerHTML='<span data-mobile-status>Проверяю связь…</span><button type="button" data-mobile-refresh>Обновить</button>';
  $('.site-header')?.after(line);
  if($('.sidebar')){const p=$('.sidebar');p.setAttribute('aria-hidden','true');p.inert=true;}
  if(!$('.sidebar [data-action=install]'))$('.sidebar-bottom')?.insertAdjacentHTML('afterbegin','<button type="button" class="btn" data-action="install">На экран «Домой»</button>');
  refreshStatus();
 }
 function refreshStatus(ok){
  const el=$('[data-mobile-status]'),line=$('.mobile-sync');if(!el)return;
  const offline=!navigator.onLine||ok===false||syncFailures>0;
  line.dataset.status=offline?'offline':'online';
  el.textContent=offline?'Нет связи · данные могут устареть':lastSync?'Данные обновлены · '+new Date(lastSync).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'Подключение к серверу…';
 }
 function pendingSync(){if($('[data-mobile-status]'))$('[data-mobile-status]').textContent='Возвращаю связь…';}
 window.JanaMobile={toggleMenu:()=>setMenu(!$('.sidebar')?.classList.contains('open')),closeMenu:()=>setMenu(false),pendingSync};
 const oldShell=shell;shell=function(){setMenu(false);oldShell();document.body.classList.remove('login-mobile');tabs();viewport();};
 const oldRender=renderPage;renderPage=function(){oldRender();if(state.user){$$('.mobile-tabs [data-page]').forEach(b=>{const active=b.dataset.page===state.page;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});}viewport();};
 const oldLogin=renderLogin;renderLogin=function(){setMenu(false);oldLogin();root.classList.remove('mobile-menu-open','modal-open','keyboard-open');document.body.classList.add('login-mobile');};
 const oldModal=modal;modal=function(title,body){setMenu(false);oldModal(title,body);root.classList.add('modal-open');viewport();};
 const oldConnection=showConnection;showConnection=function(ok){oldConnection(ok);refreshStatus(ok);};
 const oldTheme=applyTheme;applyTheme=function(){oldTheme();const dark=state.theme==='dark'||state.theme==='auto'&&matchMedia('(prefers-color-scheme:dark)').matches;document.querySelector('meta[name=theme-color]')?.setAttribute('content',dark?'#161a16':'#f6f6f6');};applyTheme();
 openInstall=async function(){
  setMenu(false);
  const installed=matchMedia('(display-mode:standalone)').matches||navigator.standalone;
  const secure=location.protocol==='https:';
  modal('JanaМен на iPhone',`<div class="install-steps">${installed?'<div class="info-strip">Уже открыто как приложение с экрана «Домой».</div>':''}<h3>Установка из Safari</h3><ol><li>Откройте общий <strong>HTTPS-адрес</strong> платформы в Safari.</li><li>Нажмите «Поделиться» — квадрат со стрелкой вверх.</li><li>Выберите «На экран “Домой”». При необходимости прокрутите список действий.</li><li>Если есть переключатель «Открывать как веб-приложение», включите его. Нажмите «Добавить».</li><li>Откройте значок JanaМен и войдите в аккаунт.</li></ol>${!secure?'<div class="error">Сейчас открыт локальный HTTP-адрес. Для установки и работы с iPhone нужен общий HTTPS-адрес сервера. localhost на телефоне — это сам телефон.</div>':`<p class="small muted">Адрес этого сервера: <strong>${esc(location.origin)}</strong></p>`}<p>Все устройства подключаются к одному серверу. Данные обновляются примерно раз в 3 секунды, пока приложение открыто. После возвращения в приложение связь проверяется сразу.</p><p class="small muted">Без сети действия и Gemini недоступны. Фоновые push-уведомления не подключены. Встроенный браузер мессенджера лучше заменить Safari.</p></div>`);
 };
 document.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-mobile-refresh')){pendingSync();stopSync();startSync(0);}
  if(b.dataset.page&&$('.sidebar.open'))setMenu(false);
  if(b.hasAttribute('data-pwa-update')){
   if(state.busy||$('#modal').open||$('#question')?.value.trim()||document.activeElement?.matches('input,textarea,select')){toast('Завершите ввод или запрос ИИ перед обновлением.');return;}
   if(waitingWorker){reloadRequested=true;waitingWorker.postMessage({type:'SKIP_WAITING'});}
  }
 });
 document.addEventListener('keydown',e=>{
  const panel=$('.sidebar.open');if(!panel)return;
  if(e.key==='Escape'){setMenu(false);return;}
  if(e.key==='Tab'){
   const items=[...panel.querySelectorAll('button,a,input,select')].filter(n=>!n.disabled&&n.getClientRects().length);
   const first=items[0],last=items.at(-1);
   if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
  }
 });
 $('#modal').addEventListener('close',()=>{root.classList.remove('modal-open');viewport();});
 window.visualViewport?.addEventListener('resize',viewport);window.visualViewport?.addEventListener('scroll',viewport);
 window.addEventListener('resize',()=>{viewport();if(!mobile())setMenu(false);});
 document.addEventListener('focusin',viewport);document.addEventListener('focusout',()=>setTimeout(viewport,100));
 function offerUpdate(worker){waitingWorker=worker;if($('.pwa-update'))return;const el=document.createElement('div');el.className='pwa-update';el.innerHTML='<span>Есть обновление приложения.</span><button class="btn" data-pwa-update>Обновить</button>';$('.site-header')?.after(el);}
 if('serviceWorker' in navigator&&isSecureContext){
  navigator.serviceWorker.addEventListener('controllerchange',()=>{if(reloadRequested)location.reload();});
  navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).then(reg=>{
   if(reg.waiting)offerUpdate(reg.waiting);
   reg.addEventListener('updatefound',()=>{const w=reg.installing;w?.addEventListener('statechange',()=>{if(w.state==='installed'&&navigator.serviceWorker.controller)offerUpdate(w);});});
  }).catch(()=>{});
 }
 viewport();
})();

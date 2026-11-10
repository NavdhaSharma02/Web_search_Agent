const $ = id => document.getElementById(id);
let active = localStorage.getItem('recallsearch.conversation'), pending = false, conversations = [];
const date = value => new Date(value).toLocaleString([], {dateStyle:'medium', timeStyle:'short'});
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {headers: {'Content-Type':'application/json'}, ...options});
  if (!response.ok) {
    let detail; try { detail = (await response.json()).detail; } catch {}
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}). Please retry.`);
  }
  return response.status === 204 ? null : response.json();
}
function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
function title() {
  $('chat-title').textContent = conversations.find(c => c.id === active)?.title || 'New conversation';
  $('delete-chat').disabled = !active || pending;
}
async function refresh() {
  conversations = await api('/conversations');
  $('conversation-count').textContent = conversations.length;
  const nav = $('conversations'); nav.replaceChildren();
  for (const conversation of conversations) {
    const button = el('button', `conversation${conversation.id === active ? ' active' : ''}`, conversation.title);
    button.title = `${conversation.title} · ${date(conversation.updated_at)}`;
    button.disabled = pending;
    if (conversation.id === active) button.setAttribute('aria-current','page');
    button.addEventListener('click', () => load(conversation.id).catch(e => notice(e.message)));
    nav.append(button);
  }
  if (!conversations.length) nav.append(el('p','empty-history','Your next good question starts here.'));
  title();
}
function render(message) {
  const item = el('article', `message ${message.role}`), top = el('div', 'message-top');
  top.append(el('span', 'avatar', message.role === 'assistant' ? 'r' : '↗'));
  top.append(el('strong','',message.role === 'assistant' ? 'RecallSearch' : 'You'));
  const timestamp = el('time','',date(message.created_at)); timestamp.dateTime = message.created_at; top.append(timestamp);
  const content = el('div', 'message-content');
  const metadata = message.metadata || {}, sources = metadata.sources || [];
  // Render text nodes and only server-verified citation URLs. No model HTML/Markdown execution.
  for (const part of message.content.split(/(\[S\d+\])/g)) {
    const source = sources.find(s => `[${s.id}]` === part);
    if (source && /^https?:\/\//.test(source.url)) {
      const link = el('a','citation',part); link.href=source.url; link.target='_blank'; link.rel='noopener noreferrer'; link.title=source.title; content.append(link);
    } else content.append(document.createTextNode(part));
  }
  item.append(top,content);
  if (metadata.memories?.length) {
    const box = el('details','memory-note'); box.append(el('summary','',`◷ Remembered user context · ${metadata.memories.length}`));
    for (const memory of metadata.memories) { const p=el('p','',`“${memory.content}”`); p.append(el('br'),el('time','',date(memory.created_at))); box.append(p); }
    item.append(box);
  }
  if (sources.length) {
    const box = el('details', 'evidence');
    box.append(el('summary','',`↗ ${sources.length} web source${sources.length===1?'':'s'}${metadata.mode==='cached_search'?' · reused recent evidence':''}`));
    for (const source of sources) {
      const link = el('a','source',`[${source.id}] ${source.title}`); link.href=source.url; link.target='_blank'; link.rel='noopener noreferrer';
      link.append(el('span','',new URL(source.url).hostname),el('small','',`Retrieved ${date(source.retrieved_at)}`)); box.append(link);
    }
    if (metadata.search_query) box.append(el('div','source',`Search: ${metadata.search_query}`));
    item.append(box);
  }
  if (message.role==='assistant') {
    const mode = {search:'Web search', memory:'Conversation response', cached_search:'Recent web evidence', error:'Could not complete'}[metadata.mode] || 'Conversation response';
    item.append(el('div','turn-meta',`${mode} · ${((metadata.latency_ms||0)/1000).toFixed(1)}s`));
  }
  $('messages').append(item); $('welcome').hidden=true;
}
function scrollBottom() { $('scroll-area').scrollTop=$('scroll-area').scrollHeight; }
async function load(id) {
  if (pending) return;
  const messages = await api(`/conversations/${id}/messages`);
  active=id; localStorage.setItem('recallsearch.conversation',id);
  $('messages').replaceChildren(); $('welcome').hidden=!!messages.length;
  for (const message of messages) render(message);
  document.body.classList.remove('sidebar-open'); notice(); await refresh(); scrollBottom();
}
function newConversation() {
  if (pending) return;
  active=null; localStorage.removeItem('recallsearch.conversation');
  $('messages').replaceChildren(); $('welcome').hidden=false;
  document.body.classList.remove('sidebar-open'); notice(); refresh().catch(e=>notice(e.message)); $('message').focus();
}
function setPending(value) {
  pending=value; $('send').disabled=value; $('new-chat').disabled=value; $('message').disabled=value;
  $('thinking').hidden=!value; document.querySelectorAll('.conversation').forEach(b=>b.disabled=value); title();
}
$('composer').addEventListener('submit', async event => {
  event.preventDefault(); const text=$('message').value.trim(); if (!text || pending) return;
  notice(); setPending(true);
  try {
    if (!active) { const conversation=await api('/conversations',{method:'POST'}); active=conversation.id; localStorage.setItem('recallsearch.conversation',active); }
    render({role:'user', content:text, created_at:new Date().toISOString()});
    $('message').value=''; $('message').style.height='auto'; $('char-count').textContent='0 / 4,000'; scrollBottom();
    const answer=await api(`/conversations/${active}/messages`,{method:'POST',body:JSON.stringify({message:text})});
    render(answer);
  } catch (error) {
    notice(`${error.message} Reload this conversation to check whether your message was saved before retrying.`);
    $('message').value=text;
  } finally { setPending(false); await refresh().catch(e=>notice(e.message)); scrollBottom(); $('message').focus(); }
});
$('message').addEventListener('keydown', event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('composer').requestSubmit();}});
$('message').addEventListener('input',()=>{const input=$('message');input.style.height='auto';input.style.height=`${Math.min(input.scrollHeight,180)}px`;$('char-count').textContent=`${input.value.length} / 4,000`;});
$('new-chat').addEventListener('click',newConversation);
$('menu').addEventListener('click',()=>document.body.classList.toggle('sidebar-open'));
document.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>{$('message').value=button.dataset.prompt;$('message').dispatchEvent(new Event('input'));$('message').focus();}));
$('delete-chat').addEventListener('click',()=>{if(active&&!pending)$('delete-dialog').showModal();});
$('cancel-delete').addEventListener('click',()=>$('delete-dialog').close());
$('confirm-delete').addEventListener('click',async()=>{try{await api(`/conversations/${active}`,{method:'DELETE'});$('delete-dialog').close();newConversation();}catch(error){notice(error.message);$('delete-dialog').close();}});
document.addEventListener('keydown',event=>{if(event.key==='n'&&!event.ctrlKey&&!event.metaKey&&!/INPUT|TEXTAREA/.test(event.target.tagName)&&!$('delete-dialog').open)newConversation();});
(async()=>{try{const health=await api('/health');$('setup').hidden=health.configured;await refresh();if(active&&conversations.some(c=>c.id===active))await load(active);else newConversation();}catch(error){notice(`Cannot connect to RecallSearch. ${error.message}`);}})();

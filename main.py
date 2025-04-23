<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>N3XUS LEAKS</title>
  <!-- Google Font -->
  <link href="https://fonts.googleapis.com/css?family=Montserrat:400,600,700&display=swap" rel="stylesheet"/>
  <!-- Font Awesome -->
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
  <style>
    :root {
      --bg-dark: #0d0d0f;
      --bg-darker: #131318;
      --text-light: #e1e1e6;
      --text-muted: #7a7a8c;
      --accent: #e6007e;
      --accent-hover: #ff1a95;
      --sidebar-width: 240px;
    }
    * { margin:0; padding:0; box-sizing:border-box; font-family:'Montserrat',sans-serif; }
    body { display:flex; min-height:100vh; background:var(--bg-dark); color:var(--text-light); }
    a { text-decoration:none; color:inherit; }

    /* Sidebar */
    .sidebar {
      position:fixed; top:0; left:0;
      width:var(--sidebar-width); height:100%;
      background:var(--bg-darker);
      display:flex; flex-direction:column; padding-top:20px;
    }
    .sidebar ul { list-style:none; padding:0 20px; }
    .sidebar li + li { margin-top:12px; }
    .sidebar li a {
      display:flex; align-items:center;
      padding:12px 16px; border-radius:4px;
      transition: background .2s;
    }
    .sidebar li a:hover, .sidebar li a.active {
      background: rgba(230,0,126,0.1);
    }
    .sidebar i { margin-right:12px; font-size:18px; }

    /* Main panel */
    .main {
      margin-left:var(--sidebar-width);
      flex:1; display:flex; flex-direction:column;
    }

    /* Header */
    .header {
      height:60px; background:var(--bg-darker);
      display:flex; align-items:center;
      justify-content:space-between; padding:0 20px;
    }
    #logo { height:40px; }
    #search-form { display:flex; align-items:center; }
    #search-input {
      padding:6px 10px; font-size:14px;
      border:none; border-radius:4px 0 0 4px; width:200px;
    }
    #search-btn {
      padding:6px 12px; border:none; border-radius:0 4px 4px 0;
      background:var(--accent); color:#fff; cursor:pointer;
      transition: background .2s;
    }
    #search-btn:hover { background:var(--accent-hover); }

    /* Intro */
    #intro {
      padding:60px 40px; text-align:center;
      animation: fadeIn 1.5s ease-in;
    }
    #intro h2 {
      font-size:36px; color:var(--accent);
      margin-bottom:16px;
      animation: slideDown 1s ease-out;
    }
    #intro p {
      color:var(--text-muted); line-height:1.5; max-width:600px; margin:0 auto;
    }
    @keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
    @keyframes slideDown { from { transform:translateY(-20px); opacity:0; } to { transform:translateY(0); opacity:1; } }

    .content { flex:1; overflow-y:auto; }

    /* Models Section */
    .models-section { padding:20px 40px; display:none; }
    #model-list-tools {
      display:flex; align-items:center; flex-wrap:wrap;
      gap:8px; margin-bottom:16px;
    }
    #model-filter-input {
      padding:6px 10px; font-size:14px; border:none;
      border-radius:4px; width:200px;
    }
    #model-az-list button {
      background:none; border:none; color:var(--accent);
      cursor:pointer; font-size:14px; padding:4px 6px;
      border-radius:4px; transition:background .2s;
    }
    #model-az-list button:hover { background:rgba(230,0,126,0.1); }

    .model-cards {
      display:grid; gap:16px;
      grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
    }
    .model-card {
      background:var(--bg-darker); border-radius:4px; overflow:hidden;
      cursor:pointer; transition:transform .1s;
    }
    .model-card:hover { transform:scale(1.02); }
    .model-card img {
      width:100%; height:120px; object-fit:cover;
    }
    .model-card .info {
      padding:8px; text-align:center;
    }
    .model-card .info h3 {
      font-size:14px; margin-bottom:4px; color:var(--text-light);
    }
    .model-card .info p {
      font-size:12px; color:var(--text-muted);
    }

    /* Gallery subview */
    #gallery-view { display:none; padding:20px 40px; }
    #back-btn {
      background:none; border:none; color:var(--accent);
      cursor:pointer; margin-bottom:16px; font-size:14px;
    }
    .endpoint-section { margin-bottom:24px; }
    .endpoint-section h3 { font-size:18px; margin-bottom:8px; color:var(--accent); }
    .items-grid {
      display:grid; gap:16px;
      grid-template-columns:repeat(auto-fill,minmax(120px,1fr));
    }
    .items-grid img {
      width:100%; height:auto; border-radius:4px; display:block;
    }

    /* FAQ Accordion */
    .accordion { max-width:800px; margin:40px auto; }
    .accordion-item {
      background:var(--bg-darker); border-radius:4px;
      margin-bottom:16px; overflow:hidden;
    }
    .accordion-item button {
      width:100%; background:none; border:none;
      color:var(--text-light); text-align:left;
      padding:20px; font-size:16px;
      display:flex; justify-content:space-between;
      align-items:center; cursor:pointer;
      transition: background .2s;
    }
    .accordion-item button:hover { background:rgba(255,255,255,0.05); }
    .accordion-item button i {
      font-size:20px; transition:transform .3s;
    }
    .panel {
      max-height:0; overflow:hidden;
      transition:max-height .3s ease;
      background:var(--bg-dark);
    }
    .panel p { padding:0 20px 20px; color:var(--text-muted); }

    /* Terms */
    #terms {
      max-width:800px; margin:40px auto;
      color:var(--text-muted); line-height:1.5; padding:0 20px;
    }

    /* Footer */
    .footer {
      background:var(--bg-darker);
      padding:40px 20px; color:var(--text-muted);
      display:flex; justify-content:space-between; flex-wrap:wrap;
    }
    .footer .left { max-width:600px; }
    .footer .left h3 { color:#fff; margin-bottom:8px; }
    .footer .links { list-style:none; display:flex; flex-wrap:wrap; margin-top:16px; }
    .footer .links li { margin-right:16px; margin-bottom:8px; }
    .footer .payments i { margin-right:12px; font-size:24px; }

    /* Back to top */
    .back-to-top {
      position:fixed; bottom:20px; right:50%;
      transform:translateX(50%);
      background:var(--accent); width:48px; height:48px;
      border-radius:50%; display:flex; align-items:center;
      justify-content:center; color:#fff; cursor:pointer;
      transition:background .2s;
    }
    .back-to-top:hover { background:var(--accent-hover); }
  </style>
</head>
<body>

  <!-- Sidebar -->
  <aside class="sidebar">
    <ul>
      <li><a href="#" class="active"><i class="fas fa-star"></i> N3XUS LEAKS</a></li>
      <li><a href="#" id="menu-models"><i class="fas fa-user"></i> Models</a></li>
      <li><a href="#faq"><i class="fas fa-question-circle"></i> FAQ</a></li>
      <li><a href="#terms"><i class="fas fa-file-alt"></i> Terms</a></li>
    </ul>
  </aside>

  <!-- Main panel -->
  <div class="main">
    <header class="header">
      <div><h1 style="display:inline-block; color:var(--accent);">N3XUS LEAKS</h1></div>
      <img id="logo" src="" alt=""/>
      <form id="search-form">
        <input id="search-input" placeholder="Search term…" autocomplete="off"/>
        <button type="submit" id="search-btn"><i class="fas fa-search"></i></button>
      </form>
    </header>

    <div class="content">
      <section id="intro">
        <h2>Welcome to N3XUS LEAKS</h2>
        <p>
          Search any creator name and instantly pull galleries across multiple leak-sites.
          The results are stored locally so you can browse even if the internet goes down.
          Simply enter a search term above and view thumbnails; click a card to open all links.
        </p>
      </section>

      <!-- MODELS SECTION -->
      <section class="models-section" id="models-section">
        <div id="model-list-tools">
          <input id="model-filter-input" type="text" placeholder="Filter models…"/>
          <div id="model-az-list"></div>
        </div>
        <div class="model-cards" id="models-grid"></div>
      </section>

      <!-- GALLERY / ALBUM LINKS VIEW -->
      <section id="gallery-view">
        <button id="back-btn"><i class="fas fa-arrow-left"></i> Back to models</button>
        <h2 id="model-title"></h2>
        <div id="album-links"></div>
      </section>

      <!-- FAQ -->
      <section id="faq" class="accordion">
        <div class="accordion-item">
          <button>What does this site do? <i class="fas fa-plus"></i></button>
          <div class="panel"><p>Aggregates publicly-available galleries from multiple sources. Search any term to see results.</p></div>
        </div>
        <div class="accordion-item">
          <button>How does offline work? <i class="fas fa-plus"></i></button>
          <div class="panel"><p>Results are saved in your browser’s LocalStorage so you can revisit them without reloading.</p></div>
        </div>
        <div class="accordion-item">
          <button>Is this legal? <i class="fas fa-plus"></i></button>
          <div class="panel"><p>We simply link to public content. We do not host any copyrighted material.</p></div>
        </div>
      </section>

      <!-- TERMS -->
      <section id="terms">
        <h2>Terms &amp; Conditions</h2>
        <p>By using this site you agree not to redistribute copyrighted content. N3XUS LEAKS is not responsible for external site availability.</p>
      </section>
    </div>

    <!-- Footer -->
    <footer class="footer">
      <div class="left">
        <h3>N3XUS LEAKS</h3>
        <p>Your one-stop aggregator for leak galleries across the web. No subscriptions, no logins—just search and browse.</p>
        <ul class="links">
          <li><a href="#faq">FAQ</a></li>
          <li><a href="#terms">Terms</a></li>
          <li><a href="#">Privacy</a></li>
          <li><a href="#">Contact</a></li>
        </ul>
        <div class="payments">
          <i class="fab fa-bitcoin"></i>
          <i class="fas fa-dollar-sign"></i>
          <i class="fab fa-cc-paypal"></i>
          <i class="fab fa-cc-visa"></i>
          <i class="fab fa-cc-mastercard"></i>
          <i class="fab fa-cc-amex"></i>
        </div>
      </div>
    </footer>
  </div>

  <div class="back-to-top"><i class="fas fa-arrow-up"></i></div>

  <script>
    const intro         = document.getElementById('intro');
    const modelsSection = document.getElementById('models-section');
    const galleryView   = document.getElementById('gallery-view');
    const modelsGrid    = document.getElementById('models-grid');
    const albumLinksEl  = document.getElementById('album-links');
    const searchForm    = document.getElementById('search-form');
    const searchInput   = document.getElementById('search-input');
    const menuModels    = document.getElementById('menu-models');
    const backBtn       = document.getElementById('back-btn');
    const modelTitle    = document.getElementById('model-title');
    const faqButtons    = document.querySelectorAll('.accordion-item button');
    const backToTop     = document.querySelector('.back-to-top');

    const endpoints = [
      { name:'Erome Gallery', url: q=>`/api/erome-gallery?query=${q}`,       type:'gallery' },
      { name:'Erome Albums',  url: q=>`/api/erome-albums?username=${q}`,     type:'albums'  },
      { name:'Bunkr Gallery', url: q=>`/api/bunkr-gallery?query=${q}`,       type:'gallery' },
      { name:'Bunkr Albums',  url: q=>`/api/bunkr-albums?username=${q}`,     type:'albums'  },
      { name:'NotFans',       url: q=>`/api/notfans?search_term=${q}`,       type:'urls',   key:['urls','titles'] },
      { name:'Influencers',   url: q=>`/api/influencers?term=${q}`,          type:'urls',   key:['urls','titles'] },
      { name:'Thothub',       url: q=>`/api/thothub?term=${q}`,              type:'urls',   key:['urls','titles'] },
      { name:'DirtyShip',     url: q=>`/api/dirtyship?term=${q}`,            type:'urls',   key:['urls','titles'] },
      { name:'PimpBunny',     url: q=>`/api/pimpbunny?term=${q}`,            type:'urls',   key:['urls','titles'] },
      { name:'LeakedZone',    url: q=>`/api/leakedzone?term=${q}`,           type:'urls',   key:['urls','titles'] },
      { name:'FanslyLeaked',  url: q=>`/api/fanslyleaked?term=${q}`,         type:'urls',   key:['urls','titles'] },
      { name:'GotAnyNudes',   url: q=>`/api/gotanynudes?term=${q}`,          type:'urls',   key:['urls','titles'] },
      { name:'NSFW247',       url: q=>`/api/nsfw247?term=${q}`,             type:'urls',   key:['urls','titles'] },
      { name:'HornySimp',     url: q=>`/api/hornysimp?term=${q}`,           type:'urls',   key:['urls','titles'] },
      { name:'Porntn',        url: q=>`/api/porntn?term=${q}`,              type:'urls',   key:['urls','titles'] },
      { name:'xxBrits',       url: q=>`/api/xxbrits?term=${q}`,             type:'urls',   key:['urls','titles'] },
      { name:'BitchesGirls',  url: q=>`/api/bitchesgirls?term=${q}`,        type:'urls',   key:['urls','titles'] },
      { name:'ThotsLife',     url: q=>`/api/thotslife?term=${q}`,           type:'urls',   key:['urls','titles'] },
    ];

    let results = JSON.parse(localStorage.getItem('n3xus_results')||'[]');

    document.addEventListener('DOMContentLoaded', () => {
      if (results.length) {
        showModelsSection();
        renderModels(results);
      }
      initModelTools();
      updateModelsLayout();
    });

    menuModels.addEventListener('click', e=>{
      e.preventDefault();
      showModelsSection();
    });

    searchForm.addEventListener('submit', async e => {
      e.preventDefault();
      const term = searchInput.value.trim();
      if (!term) return;
      modelsGrid.innerHTML = `<p style="grid-column:1/-1;color:var(--text-muted)">Searching all endpoints…</p>`;
      const model = { name: term, endpoints: [] };
      await Promise.all(endpoints.map(ep => fetchEndpoint(ep, term, model)));
      if (model.endpoints.length) {
        results.push(model);
        localStorage.setItem('n3xus_results', JSON.stringify(results));
        renderModels(results);
        showModelsSection();
        modelsSection.scrollIntoView({ behavior:'smooth' });
      }
    });

    async function fetchEndpoint(ep, term, model) {
      const url = ep.url(encodeURIComponent(term));
      try {
        const res = await fetch(url);
        const data = await res.json();
        let items = [];
        if (ep.type==='gallery') {
          items = data.images||[];
        } else if (ep.type==='albums') {
          items = data.albums||[];
        } else {
          const [u,t] = [data[ep.key[0]]||[], data[ep.key[1]]||[]];
          items = u.map((url,i)=>({ url, title:t[i] }));
        }
        if (items.length) {
          model.endpoints.push({ name:ep.name, type:ep.type, items });
        }
      } catch (err) {
        console.error(`${ep.name}:`, err);
      }
    }

    function showModelsSection() {
      intro.style.display = 'none';
      galleryView.style.display = 'none';
      document.getElementById('faq').style.display = 'none';
      document.getElementById('terms').style.display = 'none';
      modelsSection.style.display = 'block';
    }

    function renderModels(list) {
      modelsGrid.innerHTML = '';
      list.forEach(model => {
        const card = document.createElement('div');
        card.className = 'model-card';
        card.innerHTML = `
          <div class="info">
            <h3>${model.name}</h3>
            <p>${model.endpoints.length} sources</p>
          </div>
        `;
        card.addEventListener('click', ()=>openGallery(model));
        modelsGrid.appendChild(card);
      });
    }

    function openGallery(model) {
      intro.style.display = 'none';
      modelsSection.style.display = 'none';
      document.getElementById('faq').style.display = 'none';
      document.getElementById('terms').style.display = 'none';
      galleryView.style.display = 'block';
      modelTitle.textContent = model.name;
      albumLinksEl.innerHTML = '';
      model.endpoints.forEach(ep => {
        const section = document.createElement('div');
        section.className = 'endpoint-section';
        const title = document.createElement('h3');
        title.textContent = `${ep.name} (${ep.items.length})`;
        section.appendChild(title);
        const grid = document.createElement('div');
        grid.className = 'items-grid';
        ep.items.forEach(item => {
          let url, thumb;
          if (typeof item === 'string') {
            url = item;
            thumb = ep.type==='gallery' ? item : '/static/album-placeholder.png';
          } else {
            url = item.url||item.link||'';
            thumb = item.thumbnail||item.url||'/static/album-placeholder.png';
          }
          if (ep.type==='gallery' || ep.type==='albums') {
            const img = document.createElement('img');
            img.src = thumb;
            img.alt = ep.name;
            const a = document.createElement('a');
            a.href = url;
            a.target = '_blank';
            a.appendChild(img);
            grid.appendChild(a);
          } else {
            const a = document.createElement('a');
            a.href = item.url;
            a.target = '_blank';
            a.textContent = item.title;
            const div = document.createElement('div');
            div.appendChild(a);
            grid.appendChild(div);
          }
        });
        section.appendChild(grid);
        album-links          

      });
    }

    backBtn.addEventListener('click', ()=>{
      galleryView.style.display = 'none';
      modelsSection.style.display = 'block';
    });

    faqButtons.forEach(btn=>{
      btn.addEventListener('click', ()=>{
        const panel = btn.nextElementSibling, icon = btn.querySelector('i');
        document.querySelectorAll('.panel').forEach(p=>p.style.maxHeight = null);
        document.querySelectorAll('.accordion-item i').forEach(i=>i.classList.replace('fa-minus','fa-plus'));
        if (!panel.style.maxHeight) {
          panel.style.maxHeight = panel.scrollHeight+'px';
          icon.classList.replace('fa-plus','fa-minus');
        }
      });
    });

    backToTop.addEventListener('click', ()=>window.scrollTo({top:0,behavior:'smooth'}));

    function updateModelsLayout() {
      if (window.matchMedia("(min-width: 821px) and (max-width: 1180px)").matches) {
        modelsGrid.style.gridTemplateColumns = "repeat(3, 1fr)";
      } else if (window.matchMedia("(max-width: 820px)").matches) {
        modelsGrid.style.gridTemplateColumns = "repeat(1, 1fr)";
      } else {
        modelsGrid.style.gridTemplateColumns = "repeat(auto-fill,minmax(160px,1fr))";
      }
    }
    document.addEventListener("DOMContentLoaded", updateModelsLayout);
    window.matchMedia("(min-width: 821px) and (max-width: 1180px)").addEventListener("change", updateModelsLayout);
    window.matchMedia("(max-width: 820px)").addEventListener("change", updateModelsLayout);

    function initModelTools() {
      const azList = document.getElementById('model-az-list');
      'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').forEach(letter=>{
        const btn = document.createElement('button');
        btn.textContent = letter;
        btn.addEventListener('click',()=>filterModels(letter));
        azList.appendChild(btn);
      });
      const filterInput = document.getElementById('model-filter-input');
      filterInput.addEventListener('input',()=>filterModels(filterInput.value.trim()));
    }

    function filterModels(filter) {
      const cards = Array.from(modelsGrid.children);
      cards.forEach(card=>{
        const name = card.querySelector('.info h3').textContent.toLowerCase();
        if (filter.length===1 && /^[A-Z]$/.test(filter)) {
          card.style.display = name.startsWith(filter.toLowerCase()) ? 'block' : 'none';
        } else if (filter.length>1) {
          card.style.display = name.includes(filter.toLowerCase()) ? 'block' : 'none';
        } else {
          card.style.display = 'block';
        }
      });
    }
  </script>
</body>
</html>

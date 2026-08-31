/* ghola — the backdrop, the guide chrome, and same-page navigation.

   Every route is a real file, so a deep link and a refresh both serve a 200 and
   the site needs no 404 fallback. The navigation below is an enhancement over
   that: it swaps the main element instead of reloading, which is what keeps the
   dune field and its color from restarting on every click.

   Each page declares two things and nothing else. data-page names the route,
   and data-root is the relative path back to the site root, so nothing here
   hard-codes where the site is published. */

(function () {
  'use strict';

  // ---------- what the guides are, in reading order ----------------------

  var GUIDES = [
    { slug: 'limitations', title: 'What ghola does not do',
      when: 'before any of it',
      blurb: 'What it does badly, what it refuses to do on purpose, and what has already gone wrong. First in the reading order so you can decide against it early.' },
    { slug: 'quickstart', title: 'Quickstart',
      when: 'you want a pull request out of it today',
      blurb: 'Three steps, against a repository nobody else can see. A key, one job, and the first thing to change.' },
    { slug: 'walkthrough', title: 'The walkthrough',
      when: 'you want it part by part',
      blurb: 'A fresh clone to a pull request, then the three things you will want to change first. It assumes you have never used iii.' },
    { slug: 'ladder', title: 'The ladder',
      when: 'you are deciding where a rule belongs',
      blurb: 'A constraint has a rung: the mechanism that carries it. The one idea here that is worth taking without the rest.' },
    { slug: 'customizing', title: 'The customization contract',
      when: 'you want to change something and want to know where it lives',
      blurb: 'Every file that owns a decision, its built-in default, and the way to override it. Plus the three merge rules that surprise people.' },
    { slug: 'evals', title: 'Evals',
      when: 'you are about to edit a prompt',
      blurb: 'A test says whether a function returns the right value. An eval says whether a prompt change made the answers better or worse.' }
  ];

  var LANDING = [
    ['what', 'what it is'],
    ['start', 'start'],
    ['ladder', 'the ladder'],
    ['look', 'what it looks like'],
    ['not', 'what it does not do']
  ];

  var DUNES = [
    { h: '64vh', rate: 0.05,
      g: '#6E2E13,#A4470F,#D2761B,#8F3D12,#4A2412',
      d: 'M0 1000V96c180-52 300 34 470 12S840 22 1000 58s200 44 200 44V1000z' },
    { h: '52vh', rate: 0.09,
      g: '#A4470F,#D2761B,#E8A33D,#A4470F,#5C2A14',
      d: 'M0 1000V120c210 40 330-58 520-40s300 74 460 40 220-36 220-36V1000z' },
    { h: '40vh', rate: 0.14,
      g: '#D2761B,#E8A33D,#E7C982,#D2761B,#7A3413',
      d: 'M0 1000V126c160-70 280 30 430 44s280-70 440-58 330 40 330 40V1000z' },
    { h: '27vh', rate: 0.20,
      g: '#3A2112,#6E2E13,#A4470F,#4A2412,#23150C',
      d: 'M0 1000V140c240-64 380 46 600 40s360-72 600-30V1000z' },
    { h: '15vh', rate: 0.28,
      g: '#150D08,#23150C,#3A2112,#1B1109,#0A0705',
      d: 'M0 1000V130c200 76 340-30 560-16s400 88 640 46V1000z' }
  ];

  var SKY = '#0A0705,#170F09,#2C180D,#5A2A13,#A4470F,#5C2A14,#1B1109,#0A0705';

  // ---------- small helpers ----------------------------------------------

  var body = document.body;
  function root() { return body.dataset.root || './'; }
  function url(path) { return root() + path; }
  function page() { return body.dataset.page || 'home'; }
  function guideAt(slug) {
    for (var i = 0; i < GUIDES.length; i++) if (GUIDES[i].slug === slug) return i;
    return -1;
  }
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function slugify(text) {
    return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }

  // ---------- the backdrop, built once and never rebuilt ------------------

  function buildBackdrop() {
    var box = el('div', null, '');
    box.id = 'dunes';
    box.setAttribute('aria-hidden', 'true');

    var sky = el('div');
    sky.id = 'sky';
    sky.style.setProperty('--g', 'linear-gradient(180deg,' + SKY + ')');
    box.appendChild(sky);

    var sun = el('div');
    sun.id = 'sun';
    box.appendChild(sun);

    DUNES.forEach(function (d) {
      var mask = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'"
        + " viewBox='0 0 1200 1000' preserveAspectRatio='none'%3E%3Cpath d='"
        + d.d + "'/%3E%3C/svg%3E\")";
      var n = el('div', 'dune');
      n.dataset.rate = d.rate;
      n.style.setProperty('--h', d.h);
      n.style.setProperty('--g', 'linear-gradient(180deg,' + d.g + ')');
      n.style.setProperty('--m', mask);
      box.appendChild(n);
    });

    body.insertBefore(box, body.firstChild);
    return box;
  }

  // One listener, one frame, one variable. Progress through the page sets
  // --sky, which every backdrop element reads to slide its own color ramp, and
  // the dunes additionally drift sideways so five bands read as depth.
  function parallax(box) {
    var docEl = document.documentElement;
    var dunes = [].slice.call(box.querySelectorAll('.dune'));
    var sun = box.querySelector('#sun');
    var still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    var ticking = false;

    function paint() {
      var y = window.scrollY;
      var span = Math.max(1, docEl.scrollHeight - innerHeight);
      var p = Math.min(1, y / span);

      docEl.style.setProperty('--sky', (p * 100).toFixed(2) + '%');
      if (still) { ticking = false; return; }

      // Drift is bounded on purpose. Sideways stays inside the 35% of slack
      // each dune carries off-screen, and downward stays inside the 8vh
      // overhang, so no amount of scrolling opens a gap at either edge.
      var vh = innerHeight / 100;
      dunes.forEach(function (n) {
        var r = parseFloat(n.dataset.rate);
        var x = Math.min(y * r * 0.08, innerWidth * 0.3);
        n.style.transform = 'translate3d(' + x.toFixed(1) + 'px,'
          + (p * r * 26 * vh).toFixed(1) + 'px,0)';
      });
      sun.style.transform = 'translate3d(0,' + (p * 34 * vh).toFixed(1) + 'px,0)';
      ticking = false;
    }

    addEventListener('scroll', function () {
      if (!ticking) { ticking = true; requestAnimationFrame(paint); }
    }, { passive: true });
    addEventListener('resize', paint, { passive: true });
    paint();
    return paint;
  }

  // ---------- nav and footer, rebuilt whenever the depth changes ----------

  function buildNav() {
    var old = document.querySelector('.wrap > nav');
    if (old) old.parentNode.removeChild(old);

    var links = page() === 'home'
      ? LANDING.map(function (s) {
          return '<a href="#' + s[0] + '"' + (s[0] === 'ladder' || s[0] === 'what' || s[0] === 'look' ? ' class="hide-sm"' : '') + '>' + s[1] + '</a>';
        }).join('')
      : '<a href="' + url('') + '">home</a>'
        + GUIDES.map(function (g) {
            var on = g.slug === page() ? ' on' : '';
            return '<a class="hide-sm' + on + '" href="' + url('guides/' + g.slug + '/') + '">' + g.slug + '</a>';
          }).join('');

    var guidesLink = page() === 'home'
      ? '<a href="' + url('guides/') + '">guides</a>'
      : '';

    var nav = el('nav', null,
      '<div class="row">'
      + '<a class="brand" href="' + url('') + '">ghola</a>'
      + links
      + guidesLink
      + '<span class="spacer"></span>'
      + '<a href="https://github.com/tacoda/ghola">github</a>'
      + '</div>');

    var wrap = document.querySelector('.wrap');
    wrap.insertBefore(nav, wrap.firstChild);
  }

  function buildFooter() {
    var old = document.querySelector('.wrap > footer');
    if (old) old.parentNode.removeChild(old);
    var f = el('footer', null,
      '<div class="row">'
      + '<span>ghola · MIT · built on <a href="https://iii.dev">iii</a></span>'
      + '<span class="spacer"></span>'
      + '<a href="' + url('guides/') + '">guides</a>'
      + '<a href="https://github.com/tacoda/ghola">github.com/tacoda/ghola</a>'
      + '<a href="https://www.tacoda.dev">tacoda.dev</a>'
      + '</div>');
    document.querySelector('.wrap').appendChild(f);
  }

  // ---------- the guide shell --------------------------------------------

  function buildSidebar(active) {
    return el('aside', 'side',
      '<h4>Guides</h4><ol>'
      + GUIDES.map(function (g, i) {
          var on = g.slug === active ? ' class="on"' : '';
          return '<li><a' + on + ' href="' + url('guides/' + g.slug + '/') + '">'
            + '<span class="num">' + (i + 1) + '</span>' + g.title + '</a></li>';
        }).join('')
      + '</ol>'
      + '<h4>Elsewhere</h4><ol>'
      + '<li><a href="' + url('guides/') + '">All guides</a></li>'
      + '<li><a href="' + url('') + '">The landing page</a></li>'
      + '<li><a href="https://github.com/tacoda/ghola">The code</a></li>'
      + '<li><a href="https://iii.dev/docs">iii, underneath</a></li>'
      + '</ol>');
  }

  // The chapter list is generated from the headings, so it can never disagree
  // with the page. Numbers come from CSS counters for the same reason.
  function buildChapters(article) {
    var heads = [].slice.call(article.querySelectorAll('h2:not(.plain), h3:not(.plain)'));
    if (heads.length < 3) return null;

    var items = heads.map(function (h) {
      if (!h.id) h.id = slugify(h.textContent);
      var sub = h.tagName === 'H3' ? ' class="sub"' : '';
      return '<li><a' + sub + ' href="#' + h.id + '">' + h.textContent + '</a></li>';
    });

    return el('div', 'chapters',
      '<h4>Chapters</h4><ol>' + items.join('') + '</ol>');
  }

  function buildPager(i) {
    var prev = GUIDES[i - 1];
    var next = GUIDES[i + 1];
    if (!prev && !next) return null;
    var html = '';
    if (prev) {
      html += '<a class="prev" href="' + url('guides/' + prev.slug + '/') + '">'
        + '<span class="dir">Previous</span>' + prev.title + '</a>';
    }
    if (next) {
      html += '<a class="next" href="' + url('guides/' + next.slug + '/') + '">'
        + '<span class="dir">Next</span>' + next.title + '</a>';
    }
    return el('div', 'pager', html);
  }

  function buildGuidesIndex(main) {
    var host = main.querySelector('[data-cards]');
    if (!host) return;
    host.innerHTML = GUIDES.map(function (g, i) {
      return '<a class="card" href="' + url('guides/' + g.slug + '/') + '">'
        + '<span class="num">' + (i + 1) + '</span>'
        + '<h3>' + g.title + '</h3>'
        + '<p>' + g.blurb + '</p></a>';
    }).join('');

    var rows = main.querySelector('[data-order] tbody') || main.querySelector('[data-order]');
    if (rows) {
      rows.innerHTML = '<tr><th>Page</th><th>Read it when</th></tr>'
        + GUIDES.map(function (g) {
            return '<tr><td><a href="' + url('guides/' + g.slug + '/') + '">'
              + g.title + '</a></td><td>' + g.when + '</td></tr>';
          }).join('');
    }
  }

  // Wraps whatever the page author wrote into the two-column shell. The author
  // writes a main with an article in it; everything else is assembled here.
  function decorate() {
    var main = document.querySelector('main');
    if (!main) return;

    buildNav();
    buildFooter();

    var slug = page();
    var i = guideAt(slug);

    if (slug === 'guides') buildGuidesIndex(main);

    if (i === -1) return;   // the landing page and the index style themselves

    var article = main.querySelector('article');
    main.className = 'shell';
    main.innerHTML = '';
    main.appendChild(buildSidebar(slug));

    var col = el('div', 'col');
    col.appendChild(article);
    main.appendChild(col);

    var chapters = buildChapters(article);
    if (chapters) {
      var lede = article.querySelector('.lede');
      if (lede && lede.nextSibling) article.insertBefore(chapters, lede.nextSibling);
      else article.appendChild(chapters);
    }

    var pager = buildPager(i);
    if (pager) col.appendChild(pager);
  }

  function decorateAll() {
    decorate();
    renderDiagrams();
  }

  // ---------- diagrams ---------------------------------------------------

  /* Mermaid comes from the CDN and only on pages that have a diagram, themed
     from the same palette as the rest of the page so a flowchart does not
     arrive looking like it came from somewhere else. */
  var MERMAID = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';

  var MERMAID_CONFIG = {
    startOnLoad: false,
    theme: 'base',
    darkMode: true,
    fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
    themeVariables: {
      background: '#150D08',
      fontSize: '14px',

      primaryColor: '#23150C',
      primaryTextColor: '#E7C982',
      primaryBorderColor: '#6E2E13',

      secondaryColor: '#1A100A',
      secondaryTextColor: '#F1E3CB',
      secondaryBorderColor: '#3B2515',

      tertiaryColor: '#0F0A06',
      tertiaryTextColor: '#AB9070',
      tertiaryBorderColor: '#3B2515',

      lineColor: '#A4470F',
      textColor: '#F1E3CB',
      mainBkg: '#23150C',
      nodeBorder: '#6E2E13',
      nodeTextColor: '#E7C982',
      clusterBkg: 'rgba(58,33,18,.30)',
      clusterBorder: '#3B2515',
      titleColor: '#E7C982',
      edgeLabelBackground: '#150D08',

      /* sequence diagrams */
      actorBkg: '#23150C',
      actorBorder: '#6E2E13',
      actorTextColor: '#E7C982',
      actorLineColor: '#3B2515',
      signalColor: '#F1E3CB',
      signalTextColor: '#F1E3CB',
      labelBoxBkgColor: '#3A2112',
      labelBoxBorderColor: '#6E2E13',
      labelTextColor: '#E7C982',
      loopTextColor: '#AB9070',
      noteBkgColor: '#3A2112',
      noteBorderColor: '#A4470F',
      noteTextColor: '#F1E3CB',
      activationBkgColor: '#6E2E13',
      activationBorderColor: '#A4470F',
      sequenceNumberColor: '#0A0705',

      /* state diagrams */
      labelColor: '#E7C982',
      altBackground: '#1A100A',

      /* entity relationship diagrams */
      attributeBackgroundColorOdd: '#1A100A',
      attributeBackgroundColorEven: '#23160E'
    },
    flowchart: { curve: 'basis', padding: 16, nodeSpacing: 44, rankSpacing: 52, htmlLabels: false, useMaxWidth: true },
    sequence: { actorMargin: 56, useMaxWidth: true, mirrorActors: false, messageFontWeight: 400 },
    state: { useMaxWidth: true },
    er: { useMaxWidth: true, fill: '#23150C', stroke: '#6E2E13' }
  };

  var mermaidReady = null;

  function renderDiagrams() {
    var nodes = [].slice.call(document.querySelectorAll('.mermaid:not([data-done])'));
    if (!nodes.length) return;

    if (!mermaidReady) {
      mermaidReady = import(MERMAID).then(function (mod) {
        mod.default.initialize(MERMAID_CONFIG);
        return mod.default;
      });
    }

    mermaidReady.then(function (m) {
      nodes.forEach(function (n) { n.setAttribute('data-done', '1'); });
      return m.run({ nodes: nodes });
    }).catch(function () {
      // The CDN did not answer. Show the source rather than an empty panel.
      nodes.forEach(function (n) { n.setAttribute('data-done', 'failed'); });
    });
  }

  // ---------- navigation without a reload --------------------------------

  function samePage(a) {
    if (!a || a.target === '_blank' || a.hasAttribute('download')) return false;
    if (a.origin !== location.origin) return false;
    var ext = a.pathname.split('/').pop();
    return ext === '' || ext.slice(-5) === '.html';
  }

  var repaint;

  function go(href, push) {
    fetch(href, { headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.text();
      })
      .then(function (text) {
        var doc = new DOMParser().parseFromString(text, 'text/html');
        var main = doc.querySelector('main');
        if (!main) throw new Error('no main');

        if (push) history.pushState({}, '', href);

        document.title = doc.title;
        body.className = doc.body.className;
        body.dataset.page = doc.body.dataset.page || 'home';
        body.dataset.root = doc.body.dataset.root || './';

        var current = document.querySelector('main');
        current.parentNode.replaceChild(main, current);

        decorateAll();
        scrollTo(0, 0);
        if (repaint) repaint();
      })
      .catch(function () { location.href = href; });
  }

  addEventListener('click', function (e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    var a = e.target.closest && e.target.closest('a');
    if (!samePage(a)) return;
    if (a.pathname === location.pathname) return;   // an anchor on this page
    e.preventDefault();
    go(a.href, true);
  });

  addEventListener('popstate', function () { go(location.href, false); });

  // ---------- go ---------------------------------------------------------

  repaint = parallax(buildBackdrop());
  decorateAll();
})();

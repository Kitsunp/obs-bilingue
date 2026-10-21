/* Run with Node and Playwright available on NODE_PATH. Uses no OBS session. */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');

(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--disable-gpu']});
  try{
    const page=await browser.newPage({viewport:{width:620,height:520}});
    const state={revision:0,segment:1,final:false,translation_enabled:true,
      translation_display_color:'#FFD166',style:{font_face:'Arial',font_size:30,font_flags:0,
        translation_use_original_font:false,translation_font_face:'Arial',translation_font_size:25,
        translation_font_flags:0,translation_show_language_labels:false,background_color:'#10151B',
        background_opacity:78,stack:true,max_rows:3,max_lines_per_language:2,show_original:true},
      rows:[{id:1,source:'',es:'',language:'en',color:'#7CC7FF',spans:[]}]};
    const html=fs.readFileSync(path.join(root,'web/overlay.html'),'utf8').replaceAll('__LANG__','original');
    await page.route('http://caption-layout.test/**',r=>r.fulfill({
      contentType:r.request().url().endsWith('/api/state')?'application/json':'text/html',
      body:r.request().url().endsWith('/api/state')?JSON.stringify(state):html}));
    await page.goto('http://caption-layout.test/');
    async function render(source,language='en',translation=''){
      const row=state.rows[0];row.source=source;row.language=language;row.es=translation;
      row.spans=[{text:source,language,color:row.color}];state.revision++;
      await page.waitForFunction(revision=>lastKey.startsWith('['+revision+','),state.revision);
    }
    async function lines(selector='.row > div:first-child'){
      return page.locator(selector).evaluate(block=>{
        const walker=document.createTreeWalker(block,NodeFilter.SHOW_TEXT),lines=[];let node;
        while(node=walker.nextNode())for(let i=0;i<node.length;i++){
          if(/\s/u.test(node.textContent[i]))continue;
          const range=document.createRange();range.setStart(node,i);range.setEnd(node,i+1);
          const rect=range.getBoundingClientRect();let line=lines.find(l=>Math.abs(l.y-rect.y)<1);
          if(!line){line={y:rect.y,text:''};lines.push(line);}line.text+=node.textContent[i];
        }
        return lines.map(l=>l.text);
      });
    }
    const samples=[
      ['en','We keep speaking with brief pauses and continue with the same idea.'],
      ['es','Seguimos hablando con pausas breves y continuamos con la misma idea.'],
      ['fr','Nous parlons avec de courtes pauses et continuons avec la même idée.']
    ];
    for(const [language,text] of samples){
      await render(text,language);const expected=await lines();
      for(const separator of ['   ','\t','\n']){
        await render(text.replaceAll(' ',separator),language);
        assert.deepEqual(await lines(),expected,language+' whitespace changed visible words or wrapping');
      }
      await render(text,language,'Seguimos hablando con pausas breves y continuamos con la misma idea.');
      assert.deepEqual(await lines(),expected,'Late translation changed original wrapping');
    }
    const original=samples[0][1],translation=samples[1][1];
    await render(original,'en',translation);const expectedTranslation=await lines('.translation');
    await render(original,'en',translation.replaceAll(' ','\n   '));
    assert.deepEqual(await lines('.translation'),expectedTranslation,'Translation whitespace changed wrapping');
    state.rows[0].spans=[{text:'We keep speaking ',language:'en',color:'#7CC7FF'},
      {text:original.slice(17),language:'es',color:'#FFD166'}];state.revision++;
    await page.waitForFunction(revision=>lastKey.startsWith('['+revision+','),state.revision);
    const mixedLines=await lines();
    assert.deepEqual(await page.locator('.row > div:first-child > span').evaluateAll(
      spans=>spans.map(span=>getComputedStyle(span).color)),['rgb(124, 199, 255)','rgb(255, 209, 102)']);
    await render(original);assert.deepEqual(mixedLines,await lines());
    state.rows=[
      {id:1,flow_group:1,source:'We keep talking.',es:'Seguimos hablando.',language:'en',color:'#7CC7FF',
        spans:[{text:'We keep talking.',language:'en',color:'#7CC7FF'}]},
      {id:2,flow_group:1,source:'and continue without a break.',es:'',language:'en',color:'#7CC7FF',
        spans:[{text:'and continue without a break.',language:'en',color:'#7CC7FF'}]}];
    state.segment=2;state.revision++;
    await page.waitForFunction(revision=>lastKey.startsWith('['+revision+','),state.revision);
    assert.equal(await page.locator('.row').count(),1,'Technical endpoint created a new visual block');
    assert.equal(await page.locator('.row > div').first().textContent(),
      'We keep talking. and continue without a break.');
    state.rows[1].es='y continuamos sin pausa.';state.revision++;
    await page.waitForFunction(revision=>lastKey.startsWith('['+revision+','),state.revision);
    assert.equal(await page.locator('.translation').textContent(),'Seguimos hablando. y continuamos sin pausa.');
    state.rows.shift(); // TTL removal need not change the engine's current revision.
    await page.waitForFunction(()=>document.querySelector('.translation')?.textContent==='y continuamos sin pausa.');
    assert.equal(await page.locator('.translation').textContent(),'y continuamos sin pausa.');
    assert.equal(await page.locator('.row > div').first().textContent(),'and continue without a break.');
    state.rows.push({id:3,flow_group:3,source:'Una frase nueva.',es:'',language:'es',color:'#FFD166',
      spans:[{text:'Una frase nueva.',language:'es',color:'#FFD166'}]});state.segment=3;state.revision++;
    await page.waitForFunction(revision=>lastKey.startsWith('['+revision+','),state.revision);
    assert.equal(await page.locator('.row').count(),2,'Natural utterance boundary was merged');
    state.rows=state.rows.slice(-1);
    for(const [language,text] of [['ja','今日は日本語で話しながら字幕の表示を確認しています。'],
                                 ['ko','오늘은 한국어로 이야기하면서 자막 표시를 확인합니다.'],
                                 ['ar','نتحدث الآن للتحقق من عرض الترجمة أثناء الكلام.']]){
      await render(text.repeat(8),language);
      assert.ok((await lines()).length<=2,language+' line limit exceeded');
    }
    await render('x'.repeat(200));assert.ok((await lines()).length<=2,'Long token exceeded line limit');
    state.style.translation_show_language_labels=true;
    await render(original,'en',translation);assert.equal(await page.locator('.language-label').count(),2);
    assert.ok((await lines()).length<=2);assert.ok((await lines('.translation')).length<=2);
    await page.screenshot({path:path.join(root,'verification/line-layout.png')});
    const report={passed:true,scope:'Actual overlay in headless Chromium; controlled state, no acoustic claim',
      whitespace_variants_preserve_wrap_and_visible_words:['en','es','fr'],
      translation_whitespace_verified:true,late_translation_preserves_original_wrap:true,
      colored_spans_preserve_wrap:true,line_limits_verified:['ja','ko','ar','long-token'],
      technical_endpoints_continue_same_block:true,natural_endpoints_keep_separate_blocks:true,
      expired_original_and_translation_removed_together:true,
      separate_original_and_spanish_blocks:true};
    fs.writeFileSync(path.join(root,'verification/line-layout.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

import { useState } from 'react';
import { Brand } from './components/Brand';
import { Button } from './components/ui/Button';
import { GlassSurface } from './components/ui/GlassSurface';
import { Input } from './components/ui/Input';

// Step 1 only: a component/visual-system preview, not a working chat screen.
export function App() {
  const [question, setQuestion] = useState('');
  const [previewed, setPreviewed] = useState(false);

  return (
    <div className="foundation">
      <div className="ambient" aria-hidden="true"><div className="ambient__ribbon" /></div>
      <header className="preview-header">
        <Brand />
        <span className="preview-badge"><span />Design preview</span>
      </header>

      <main id="main-content" className="preview-main">
        <section className="intro" aria-labelledby="preview-title">
          <span className="eyebrow">2026 / F1 REGULATIONS</span>
          <h1 id="preview-title">Clarity.<br /><span>At speed.</span></h1>
          <p>A sharper perspective on the rules.</p>
        </section>

        <section className="system-preview" aria-label="Visual system preview">
          <div className="section-label"><span>01 / MATERIALS</span><span>Less noise. More clarity.</span></div>
          <div className="material-grid">
            <GlassSurface className="material material--clear">
              <span className="material__number">01</span>
              <div><h2>Clear</h2><p>Floating surfaces</p></div>
            </GlassSurface>
            <GlassSurface tone="smoked" className="material material--smoked">
              <span className="material__number">02</span>
              <div><h2>Smoked</h2><p>Quiet navigation</p></div>
            </GlassSurface>
            <GlassSurface tone="reading" className="material material--reading">
              <span className="material__number">03</span>
              <div><h2>Solid</h2><p>Space to read</p></div>
            </GlassSurface>
          </div>

          <GlassSurface className="control-preview">
            <div className="section-label"><span>02 / CONTROLS</span><span>Made for focus</span></div>
            <Input label="Question preview" placeholder="Ask about the rules…" value={question}
              onChange={(event) => { setQuestion(event.target.value); setPreviewed(false); }}
              maxLength={4000} autoComplete="off" />
            <div className="control-preview__actions">
              <div className="button-group">
                <Button disabled={!question.trim()} onClick={() => setPreviewed(true)}>
                  Preview <span aria-hidden="true">↗</span>
                </Button>
                <Button variant="glass" onClick={() => { setQuestion(''); setPreviewed(false); }}>Reset</Button>
              </div>
              <p role="status" className="preview-status">
                {previewed ? 'Controls ready. Chat comes next.' : 'Visual preview only. No requests sent.'}
              </p>
            </div>
          </GlassSurface>
        </section>
      </main>
      <footer className="preview-footer"><span>Independent project. Not affiliated with FIA or Formula 1.</span><span>FOUNDATION / 01</span></footer>
    </div>
  );
}

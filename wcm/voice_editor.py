"""Voice editor UI; binary parsing and conversion live in voices.py."""
from pathlib import Path
import io, tempfile, re
from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QTreeWidget,
    QTreeWidgetItem,QHeaderView,QPushButton,QFileDialog,QMessageBox,QAbstractItemView)
from .voices import event_label, wav_pcm, wav_bytes, MAX_AUDIO, map_wavs

def event_category(label):
    words=set(re.findall(r'[a-z]+',label.casefold()))
    for category,tokens in (('Boost',{'boost','dash'}),('Jump',{'jump','jumpaction','trick'}),('Attack',{'attack'}),('Damage',{'damage','hurt','hit','crash','fall','spin'}),('Victory',{'victory','win','goal','finish','god','top'})):
        if words & tokens:return category
    return 'Other'

class VoiceEditor(QDialog):
    def __init__(self,session,parent=None):
        super().__init__(parent);self.session=session;self.setWindowTitle('Character Voice Editor')
        self.resize(960,660);self.temp=tempfile.TemporaryDirectory(prefix='rrcm-voice-');self.play_count=0
        self.player=QMediaPlayer(self);self.output=QAudioOutput(self);self.player.setAudioOutput(self.output)
        self.player.errorOccurred.connect(lambda error,message:self.status.setText('Playback unavailable: '+message))
        layout=QVBoxLayout(self)
        title=QLabel(f'{session.pack.inventory.skins[session.code,session.slot].name or session.code.upper()} · Slot {session.slot}')
        title.setStyleSheet('font-size: 16pt; font-weight: 700');layout.addWidget(title)
        self.search=QLineEdit();self.search.setPlaceholderText('Search voice events or groups…');self.search.textChanged.connect(self.filter_rows);layout.addWidget(self.search)
        self.table=QTreeWidget();self.table.setColumnCount(5)
        self.table.setHeaderLabels(['Voice event','BRSAR file ID','Wave index','Group','Status'])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.header().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for col in (1,2,3,4):self.table.header().setSectionResizeMode(col,QHeaderView.ResizeMode.ResizeToContents)
        self.items={};categories={}
        for key,index in session.rows:
            bank=session.archive.banks[key];label=event_label(bank,index);category=event_category(label)
            if category not in categories:
                categories[category]=QTreeWidgetItem(self.table,[category]);categories[category].setExpanded(True)
            item=QTreeWidgetItem(categories[category],[label,str(bank.file_id),str(index),key,''])
            item.setData(0,Qt.ItemDataRole.UserRole,(key,index));self.items[key,index]=item
            item.setToolTip(0,'\n'.join(f'{name} (event ID {sid})' for sid,name in bank.labels.get(index,[])))
            item.setToolTip(1,f'[{bank.file_id}]/Audio[{index}].wav')
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.itemDoubleClicked.connect(lambda item,col:self.preview())
        layout.addWidget(self.table,1)
        self.controls=QHBoxLayout();layout.addLayout(self.controls)
        self.add_button('▶ Play',self.preview)
        self.add_button('Play Original',lambda:self.preview(original=True))
        self.add_button('Stop',self.player.stop)
        self.replace_button=self.add_button('Replace WAV…',self.replace)
        self.restore_button=self.add_button('Restore Original',self.restore)
        imports=QHBoxLayout();layout.addLayout(imports)
        self.folder_button=self.add_button('Import WAV Folder…',lambda:self.import_folder(),imports)
        self.source_button=self.add_button('Import Stored WAVs…',self.import_sources,imports)
        self.manual_button=self.add_button('Map Unrecognized WAV…',self.map_unmatched,imports)
        self.unmatched=[];self.manual_button.setEnabled(False)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        footer=QHBoxLayout();layout.addLayout(footer);footer.addStretch()
        self.revert_button=self.add_button('Revert',self.revert,footer)
        self.save_button=self.add_button('Save',self.save,footer)
        self.add_button('Close',self.close,footer)
        self.changed=False;self.refresh();self.table.setCurrentItem(next(iter(self.items.values()),None))
        if not session.editable:self.status.setText('Read-only distribution character. Enable Developer Mode to edit voices.')
    def add_button(self,label,callback,row=None):
        button=QPushButton(label);button.clicked.connect(callback);(row or self.controls).addWidget(button);return button
    def selected_events(self):
        targets=set()
        for item in self.table.selectedItems():
            target=item.data(0,Qt.ItemDataRole.UserRole)
            if target and not item.isHidden():targets.add(tuple(target))
            elif not target:
                for i in range(item.childCount()):
                    child=item.child(i)
                    if not child.isHidden():targets.add(tuple(child.data(0,Qt.ItemDataRole.UserRole)))
        return [t for t in self.session.rows if t in targets]
    def selected(self):return next(iter(self.selected_events()),None)
    def selection_changed(self):
        targets=self.selected_events();editable=self.session.editable and bool(targets) and all(k not in self.session.errors for k,i in targets)
        self.replace_button.setEnabled(editable);self.restore_button.setEnabled(editable)
        if hasattr(self,'manual_button'):self.manual_button.setEnabled(editable and len(targets)==1 and bool(self.unmatched))
        if hasattr(self,'status'):self.status.setText(f'{len(self.session.rows)} voice clips · {len(targets)} selected · {len(self.session.pending)} staged changes')
    def filter_rows(self,text):
        text=text.casefold();self.table.clearSelection()
        for item in self.items.values():item.setHidden(not (text in item.parent().text(0).casefold() or any(text in item.text(c).casefold() for c in range(5))))
        for i in range(self.table.topLevelItemCount()):
            parent=self.table.topLevelItem(i);parent.setHidden(all(parent.child(j).isHidden() for j in range(parent.childCount())))
            if text:parent.setExpanded(True)
        self.table.setCurrentItem(next((item for item in self.items.values() if not item.isHidden()),None));self.selection_changed()
    def refresh(self):
        for target,item in self.items.items():
            item.setText(4,self.session.state(*target))
            source=self.session.pending_sources.get(target)
            item.setToolTip(4,str(source) if source else '')
        dirty=bool(self.session.pending);self.save_button.setEnabled(dirty and self.session.editable);self.revert_button.setEnabled(dirty)
        self.folder_button.setEnabled(self.session.editable);self.source_button.setEnabled(self.session.editable);self.selection_changed()
    def play(self,raw):
        self.player.stop();self.play_count+=1;path=Path(self.temp.name)/f'preview-{self.play_count}.wav';path.write_bytes(raw)
        self.player.setSource(QUrl.fromLocalFile(str(path)));self.player.play()
        for old in Path(self.temp.name).glob('preview-*.wav'):
            if old!=path:
                try:old.unlink()
                except OSError:pass
    def preview(self,original=False):
        if not self.selected():return
        try:self.play(self.session.audio(*self.selected(),original=original))
        except Exception as exc:QMessageBox.warning(self,'Cannot preview',str(exc))
    def stage_file(self,path,source_name=None):
        if Path(path).stat().st_size>MAX_AUDIO:raise ValueError('WAV exceeds 32 MiB limit')
        raw=Path(path).read_bytes();rate,samples=wav_pcm(raw)
        # Preview the source before committing it to the selected event.
        preview=QMessageBox(self);preview.setWindowTitle('Preview replacement WAV')
        preview.setText(f'{Path(path).name}\n{rate:,} Hz · {samples.shape[1]} channel(s) · {len(samples)/rate:.2f} seconds\nReplace the selected voice event?')
        play=preview.addButton('▶ Preview WAV',QMessageBox.ButtonRole.ActionRole)
        preview.addButton(QMessageBox.StandardButton.Apply);preview.addButton(QMessageBox.StandardButton.Cancel)
        play.clicked.connect(lambda:self.play(wav_bytes(rate,samples)))
        # ActionRole closes QMessageBox, so reopen it after each preview.
        while True:
            answer=preview.exec()
            if preview.clickedButton()==play:continue
            if answer!=QMessageBox.StandardButton.Apply:return
            break
        self.session.replace(*self.selected(),raw,source_name or path);self.refresh()
    def replace(self):
        if len(self.selected_events())>1 or any(item.childCount() for item in self.table.selectedItems()):
            self.import_folder(selected_only=True);return
        path,_=QFileDialog.getOpenFileName(self,'Replace voice with WAV','','PCM WAV (*.wav)')
        if not path:return
        try:self.stage_file(path)
        except Exception as exc:QMessageBox.warning(self,'Cannot replace voice',str(exc))
    def restore(self):
        if self.selected():
            try:
                for target in self.selected_events():self.session.restore(*target)
                self.refresh()
            except Exception as exc:QMessageBox.warning(self,'Cannot restore voice',str(exc))
    def import_folder(self,selected_only=False):
        path=QFileDialog.getExistingDirectory(self,'Choose WAV folder (searched recursively)')
        if not path:return
        def entries():
            root=Path(path);result=[]
            for p in root.rglob('*'):
                if p.is_file() and p.suffix.lower()=='.wav':
                    if p.stat().st_size>MAX_AUDIO:raise ValueError(f'WAV exceeds 32 MiB limit: {p.name}')
                    result.append((p.relative_to(root).as_posix(),p.read_bytes()))
            return result
        self.import_entries(entries,set(self.selected_events()) if selected_only else None)
    def import_sources(self):
        from .mkchara import build_package,read_package
        self.import_entries(lambda:read_package(io.BytesIO(build_package(self.session.pack,self.session.code,self.session.slot))).sources)
    def import_entries(self,read,targets=None):
        from .gui import read_library_background
        try:
            entries,mapped,unmatched=read_library_background(lambda:self._map_entries(read(),targets),self,title='Mapping Voice Clips',message='Validating file IDs and wave indices…')
            self.review_bulk(entries,mapped,unmatched,targets)
        except Exception as exc:QMessageBox.warning(self,'Cannot import voices',str(exc))
    def _map_entries(self,entries,targets=None):
        mapped,unmatched=map_wavs(entries,self.session.archive)
        if targets is not None:
            unmatched += [name for t,(name,raw) in mapped.items() if t not in targets]
            mapped={t:value for t,value in mapped.items() if t in targets}
        return entries,mapped,list(dict.fromkeys(unmatched))
    def review_bulk(self,entries,mapped,unmatched,targets=None):
        from PySide6.QtWidgets import QComboBox
        dialog=QDialog(self);dialog.setWindowTitle('Review WAV assignments');dialog.resize(1000,600)
        layout=QVBoxLayout(dialog);layout.addWidget(QLabel(f'{len(mapped)} verified matches · {len(unmatched)} unmatched/conflicting files. Assign explicitly or leave unchanged.'))
        tree=QTreeWidget();tree.setHeaderLabels(['Source WAV','Detection','Assignment']);layout.addWidget(tree,1)
        allowed=[t for t in self.session.rows if (targets is None or t in targets) and t[0] not in self.session.errors]
        choices=['Leave unchanged']+[f'{event_label(self.session.archive.banks[k],i)} · [{self.session.archive.banks[k].file_id}]/Audio[{i}] · {k}' for k,i in allowed]
        byname={name:t for t,(name,raw) in mapped.items()};boxes=[]
        for name,raw in entries:
            if not name.lower().endswith('.wav'):continue
            single,_=map_wavs([(name,raw)],self.session.archive)
            detected=next(iter(single),None)
            state='Verified match' if name in byname else ('Outside selection' if detected and targets is not None and detected not in targets else 'Conflicting target' if detected else 'Unmatched / ambiguous')
            item=QTreeWidgetItem(tree,[name,state]);box=QComboBox();box.addItems(choices);target=byname.get(name)
            if target in allowed:box.setCurrentIndex(allowed.index(target)+1)
            tree.setItemWidget(item,2,box);boxes.append((name,raw,box))
        tree.header().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        def preview_source():
            item=tree.currentItem()
            if item:
                raw=next(raw for name,raw,box in boxes if name==item.text(0))
                try:rate,samples=wav_pcm(raw);self.play(wav_bytes(rate,samples))
                except Exception as exc:QMessageBox.warning(dialog,'Cannot preview',str(exc))
        self.add_button('Play WAV',preview_source,buttons);buttons.addStretch()
        self.add_button('Stage Replacements',dialog.accept,buttons);self.add_button('Cancel',dialog.reject,buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        assignments={}
        for name,raw,box in boxes:
            if not box.currentIndex():continue
            target=allowed[box.currentIndex()-1]
            if target in assignments:
                QMessageBox.warning(self,'Conflicting assignments','No changes staged. Multiple WAVs target the same event: '+name);return
            assignments[target]=(name,raw)
        self.stage_bulk(assignments)
        assigned={name for name,raw in assignments.values()}
        self.unmatched=[(name,raw) for name,raw in entries if name not in assigned and name.lower().endswith('.wav')];self.refresh()
    def stage_bulk(self,assignments):
        pending=dict(self.session.pending);sources=dict(self.session.pending_sources);raw_sources=dict(self.session.pending_raw)
        try:
            for target,(name,raw) in assignments.items():self.session.replace(*target,raw,name)
        except Exception:
            self.session.pending=pending;self.session.pending_sources=sources;self.session.pending_raw=raw_sources;raise
        self.refresh()
    def map_unmatched(self):
        from PySide6.QtWidgets import QInputDialog
        if not self.selected() or not self.unmatched:return
        names=[name for name,raw in self.unmatched]
        name,ok=QInputDialog.getItem(self,'Map WAV to selected event','Choose a clip to preview and assign:',names,0,False)
        if not ok:return
        raw=dict(self.unmatched)[name];path=Path(self.temp.name)/'manual.wav';path.write_bytes(raw)
        try:
            self.stage_file(path,name)
        except Exception as exc:QMessageBox.warning(self,'Cannot map voice',str(exc))
    def revert(self):self.session.revert();self.refresh()
    def save(self):
        from .gui import PreviewDialog,read_library_background
        try:
            plan=read_library_background(self.session.plan,self,title='Preparing Voice Changes',message='Building wave resources and preserving original WAV sources…')
            if PreviewDialog(plan,self).exec()!=QDialog.DialogCode.Accepted:return
            backup=read_library_background(lambda:self.session.pack.commit(plan),self,title='Saving Voice Changes',message='Backing up and installing voice resources…')
            # Reload the baseline/current resources so Restore/Revert stay accurate.
            from .voices import VoiceSession
            self.session=VoiceSession(self.session.pack,self.session.code,self.session.slot,self.session.archive.path)
            self.changed=True;self.refresh();self.status.setText(f'Saved successfully. Backup: {backup}')
        except Exception as exc:QMessageBox.warning(self,'Cannot save voices',str(exc))
    def closeEvent(self,event):
        if self.session.pending and QMessageBox.question(self,'Unsaved voice changes','Discard staged voice changes?')!=QMessageBox.StandardButton.Yes:
            event.ignore();return
        self.player.stop();self.player.setSource(QUrl())
        try:self.temp.cleanup()
        except OSError:pass # Windows multimedia may release its last file asynchronously.
        event.accept()
    def reject(self):self.close()

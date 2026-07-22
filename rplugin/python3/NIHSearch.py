import os
import sys
import json
import threading
from pathlib import Path
import xml.etree.ElementTree as ET

current_file = Path(__file__).resolve()

plugin_root = current_file.parents[2] 
deps_dir = plugin_root / "deps"

if deps_dir.exists() and str(deps_dir) not in sys.path:
    sys.path.insert(0, str(deps_dir))

print(deps_dir)

import requests
import pynvim
from Bio import Entrez
from pynvim.api import NvimError

@pynvim.plugin
class NIHSearch(object):
    def __init__(self, nvim):
        self.nvim = nvim
        self.sum = []
        self.active_sum = None
        Entrez.email = "NIHSearch@nvim.com"

    @pynvim.command("CloseActiveWindow", sync=True)
    def CloseActiveWindow(self):
        try:
            currWin = self.nvim.api.get_current_win()
            self.nvim.async_call(lambda: self.nvim.err_write(f"Active window handle just prior to close attempt: {currWin}"))
            self.nvim.api.win_close(currWin, False)
        except NvimError as e:
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error closing window: {e}"))
    
    @pynvim.command("CloseActiveWindowAndResetActiveSum", sync=True)
    def CloseActiveWindowAndResetActiveSum(self):
        try:
            currWin = self.nvim.api.get_current_win()
            self.nvim.async_call(lambda: self.nvim.err_write(f"Active window handle just prior to close attempt: {currWin}"))
            self.nvim.api.win_close(currWin, False)
            self.active_sum = None
        except NvimError as e:
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error closing window: {e}"))

    @pynvim.command("OpenPaperInNewWindow", sync=True)
    def OpenPaperInNewWindow(self):

        win_handle = self.nvim.current.window.handle
        buf_handle = self.nvim.current.buffer
        self.nvim.command('vsplit')

        try:
            self.nvim.api.buf_del_keymap(buf_handle, 'n', '<CR>')
            self.nvim.api.buf_del_keymap(buf_handle, 'n', '<LeftMouse>')
            self.nvim.api.buf_del_keymap(buf_handle, 'n', '<Esc>')
        except Exception as e:
            err_msg = str(e)
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error: {err_msg}\n"))   
        
        try:
            for win in self.nvim.windows:
                config = self.nvim.api.win_get_config(win.handle)
                if config.get('relative', '') != '':
                    try:
                        self.nvim.api.win_close(win.handle, True)  
                    except Exception:
                        pass
        except Exception:
            pass


    def SearchMapping(self, buf):
        opts = {'noremap': True, 'silent': True}
        buf.api.set_keymap('n', '<CR>', ':DisplayPaperSummary<CR>', opts)
        buf.api.set_keymap('n', '<LeftMouse>', '<LeftMouse>:DisplayPaperSummary<CR>', opts)
        buf.api.set_keymap('n', '<Esc>', ':CloseActiveWindow<CR>', opts)
    
    def SummaryMapping(self, buf):
        opts = {'noremap': True, 'silent': True}
        buf.api.set_keymap('n', '<CR>', ':DisplayPaper<CR>', opts)
        buf.api.set_keymap('n', '<LeftMouse>', '<LeftMouse>:DisplayPaper<CR>', opts)
        buf.api.set_keymap('n', '<Esc>', ':CloseActiveWindowAndResetActiveSum<CR>', opts)

    def PaperPreviewMapping(self, buf):
        opts = {'noremap': True, 'silent': True}
        buf.api.set_keymap('n', '<LeftMouse>', '<LeftMouse>:OpenPaperInNewWindow<CR>', opts)
        buf.api.set_keymap('n', '<CR>', ':OpenPaperInNewWindow<CR>', opts)
        buf.api.set_keymap('n', '<Esc>', ':CloseActiveWindow<CR>', opts)

    def ReturnCleanAbstractXml(self, xml):
        abstract_text = 'No Abstract Found'
        articles = xml.get("PubmedArticle", [])

        if articles:
            medline = articles[0].get("MedlineCitation", {})
            article_info = medline.get("Article", {})
            title = article_info.get("ArticleTitle", "No Title Found")
    
            abstract_dict = article_info.get("Abstract", {})
            if abstract_dict:
                fragments = abstract_dict.get("AbstractText", [])
                abstract_text = " ".join(fragments)
    
        return abstract_text

    @pynvim.command("DisplayPaper", sync=True)
    def DisplayPaper(self):
        try:
            def updateUI():
                valRow = 6
                currBuf = self.nvim.api.get_current_buf()
                currWin = self.nvim.api.get_current_win()
                row, col = self.nvim.api.win_get_cursor(currWin)
                if (row == valRow):
                    # Will hold paper preview
                    # Create new buffer
                    paperPreviewBufHandle = self.nvim.api.create_buf(False, True)
                    self.PaperPreviewMapping(paperPreviewBufHandle)
                    paperPreviewBufHandle.options['buftype'] = 'nofile'
                    paperPreviewBufHandle.options['bufhidden'] = 'wipe'
                    paperPreviewBufHandle.options['filetype'] = 'markdown'
                    paperPreviewBufHandle.options['modifiable'] = True

                    # Put doi and name of paper in the new buffer
                    title = self.active_sum.get("Title", "N/A")
                    doi = self.active_sum.get("DOI", "N/A")
                    lines = []
                    lines.append(f"DOI: {doi}")
                    lines.append("-------------------------------")

                    paperId = self.active_sum.get("Id")

                    try:
                        fetch_handle = Entrez.efetch(db="pmc", id=paperId, retmode="xml")
                        xml_data = fetch_handle.read()
                        fetch_handle.close()
                        root = ET.fromstring(xml_data)

                        paragraphs = root.findall(".//body//p")

                        if paragraphs:
                            for p in paragraphs:
                                text_content = "".join(p.itertext()).strip()
                                
                                if text_content:
                                    for line in text_content.splitlines():
                                        lines.append(line.rstrip())
                                    lines.append("") # Section paragraph spacing
                        else:
                            lines.append("[Notice]: Full-text structural body paragraphs are unavailable for this PMC archive record.")

                    except Exception as fetch_err:
                        lines.append(f"[Error fetching structural XML payload]: {fetch_err}")

                    paperPreviewBufHandle[:] = lines
                    paperPreviewBufHandle.options['modifiable'] = False

                    # Create new window over other windows, fill this new window with paperPreviewBufHandle contents
                    winWidth = self.nvim.options['columns']
                    winHeight = self.nvim.options['lines']

                    config = {
                        'relative': 'editor',
                        'row': int(winHeight / 4),
                        'col': int(winWidth / 4),
                        'width': int(winWidth / 2),
                        'height': int(winHeight / 2),
                        'border': 'rounded', 
                        'anchor': 'NW',
                        'style': 'minimal',
                        'focusable': True,
                    }
                    self.nvim.command(':set linebreak')
                    self.nvim.command(':set breakindent')
                    paperPreviewWinHandle = self.nvim.api.open_win(paperPreviewBufHandle, True, config) # Keep this here, putting it within config dosent work
                    self.nvim.api.win_set_option(paperPreviewWinHandle, 'wrap', True)
                    self.nvim.api.set_current_win(paperPreviewWinHandle) 
            self.nvim.async_call(updateUI)
        except Exception as e:
            err_msg = str(e)
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error: {err_msg}\n"))

    @pynvim.command("DisplayPaperSummary", sync=True)
    def DisplayPaperSummary(self):
        try:
            def updateUI(): 
                valRow = [i for i in range(8, 1208, 6)]
                currBuf = self.nvim.api.get_current_buf()
                currWin = self.nvim.api.get_current_win()
                row, col = self.nvim.api.win_get_cursor(currWin)
                if (row in valRow):
                    ind = valRow.index(row)
                    self.active_sum = self.sum[ind]

                    summaryBufHandle = self.nvim.api.create_buf(False, True)
                    self.SummaryMapping(summaryBufHandle)
                    summaryBufHandle.options['buftype'] = 'nofile'
                    summaryBufHandle.options['bufhidden'] = 'wipe'
                    summaryBufHandle.options['filetype'] = 'markdown'
                    summaryBufHandle.options['modifiable'] = True

                    title = self.active_sum.get('Title', 'N/A')
                    authors = self.active_sum.get('AuthorList', 'N/A')
                    datePublished = self.active_sum.get("PubDate", "N/A")
                    journal = self.active_sum.get("FullJournalName", "N/A")

                    # Abstract retrival and cleaning logic
                    paper_id = self.active_sum.get('Id')
                    paper_handle = Entrez.efetch(db='pubmed', id=paper_id, rettype="abstract", retmode="xml")
                    uncleaned_abstract_xml = Entrez.read(paper_handle)
                    paper_handle.close()
                    abstract = self.ReturnCleanAbstractXml(uncleaned_abstract_xml)

                    comment = self.active_sum.get("Comment", "N/A")
                    note = self.active_sum.get("Note", "N/A")

                    lines = []
                    lines.append(f"## {title}")
                    lines.append(f"**Date Published**: {datePublished}")
                    lines.append(f"**Journal**: {journal}")
                    lines.append(f"**Authors**: {', '.join(authors)}")
                    lines.append("")
                    lines.append("**View Full Text**")
                    lines.append("")
                    lines.append("Abstract")
                    lines.append("---")
                    lines.append(abstract) 
                    lines.append("")
                    lines.append("Comment")
                    lines.append("---")
                    lines.append(comment)
                    lines.append("")
                    lines.append("Note")
                    lines.append("---")
                    lines.append(note)

                    summaryBufHandle[:] = lines
                    summaryBufHandle.options['modifiable'] = False

                    # create new window thats overlayed over the search window & fill it with the contents of the summaryBufHandle
                    winWidth = self.nvim.options['columns']
                    winHeight = self.nvim.options['lines']

                    config = {
                        'relative': 'editor',
                        'row': int(winHeight / 4),
                        'col': int(winWidth / 4),
                        'width': int(winWidth / 2),
                        'height': int(winHeight / 2),
                        'border': 'rounded', 
                        'anchor': 'NW',
                        'style': 'minimal',
                        'focusable': True,
                    }
                    self.nvim.command(':set linebreak')
                    self.nvim.command(':set breakindent')
                    summaryWinHandle = self.nvim.api.open_win(summaryBufHandle, True, config) # Keep this here, putting it within config dosent work
                    self.nvim.api.win_set_option(summaryWinHandle, 'wrap', True)
                    self.nvim.api.set_current_win(summaryWinHandle) 

            self.nvim.async_call(updateUI)
        except Exception as e:
            err_msg = str(e)
            self.nvim.async_call(lambda: self.nvim.err_write(f"Error: {err_msg}\n"))

    @pynvim.command('NIHSearch', nargs='+', sync=False)
    def nihSearch(self, args):
        if ("-h" in args):
            def helpMenu():
                def updateUI():
                    helpBufHandle = self.nvim.api.create_buf(False, True)
                    helpBufHandle.options['buftype'] = 'nofile'
                    helpBufHandle.options['bufhidden'] = 'wipe'
                    helpBufHandle.options['filetype'] = 'markdown'

                    lines = ["# NIHSearch Help Menu", "---", ""]

                    lines.append("## Description")
                    lines.append("NIHSearch.py allows users to query different NIH databases includeing pubmed, pubmed centeral, pubmed protein database, etc. In the floating window users are free to view a short description of each item returned from a query and open the associated file in a new buffer.")
                    lines.append("")

                    lines.append("## Usage")
                    lines.append("`:NIHSearch [db (optional)] [query]`")
                    lines.append("")
                    lines.append("- `db`: String, specifies what database to querry. Valid options inlcude pubmed, protein, nuccore, gene, snp, structure, pmc (for Pubmed-Central), genome, taxonomy, mesh, and  sra. This argument is set to 'pubmed' by default.")
                    lines.append("")
                    lines.append("- `query`: String, speficies the term to querry.")

                    helpBufHandle[:] = lines
                    helpBufHandle.options['modifiable'] = False

                    winWidth = self.nvim.options['columns']
                    winHeight = self.nvim.options['lines']

                    config = {
                        'relative': 'editor',
                        'row': int(winHeight / 4),
                        'col': int(winWidth / 4),
                        'width': int(winWidth / 2),
                        'height': int(winHeight / 2),
                        'border': 'rounded', 
                        'anchor': 'NW',
                        'style': 'minimal',
                        'focusable': True,
                    }
                    self.nvim.command(':set linebreak')
                    self.nvim.command(':set breakindent')
                    helpWinHandle = self.nvim.api.open_win(helpBufHandle, True, config) # Keep this here, putting it within config dosent work
                    self.nvim.api.win_set_option(helpWinHandle, 'wrap', True)

                self.nvim.async_call(updateUI)
            threading.Thread(target=helpMenu, daemon=True).start()

        else:
            db = ''
            query = ''
            valid_dbs = ["pubmed", "protein", "nuccore", "gene", "snp", "structure", "pmc", "genome", "taxonomy", "mesh", "sra"]
        
            if (len(args) < 2):
                db = "pubmed"
                query = args[0]
            else:
                db = args[0]
                query = args[1]

            if (db not in valid_dbs):
                err_msg = "Invalid db specified. Run NIHSearch -h for usage instructions."
                self.nvim.async_call(lambda: self.nvim.err_write(f"NIH Error: {err_msg}\n"))
                return
        
            self.nvim.out_write(f"Searching NIH database {db} for: {query}...\n")

            def task():
                try:
                    # Search for ID's
                    search_handle = Entrez.esearch(db="pmc", term=query, retmax=100)
                    search_result = Entrez.read(search_handle)
                    ids = search_result.get("IdList", [])
                    search_handle.close()

                    if not ids:
                        self.nvim.err_write(f"No results found for '{query}'\n")
                        return

                    # Retrieve summaries using ID's
                    summary_handle = Entrez.esummary(db="pmc", id=",".join(ids))
                    summaries = Entrez.read(summary_handle)
                    self.sum = summaries
                    summary_handle.close()

                    # UI
                    def updateUI():

                        queryBufHandle = self.nvim.api.create_buf(False, True)
                        self.SearchMapping(queryBufHandle)
                        queryBufHandle.options['buftype'] = 'nofile'
                        queryBufHandle.options['bufhidden'] = 'wipe'
                        queryBufHandle.options['filetype'] = 'markdown'
                    
                        lines = [ f"# NIH Database ({db}) Results For: {query}", "---", ""]

                        for paper in summaries:

                            title = paper.get('Title', 'N/A')
                            authors = paper.get('AuthorList', 'N/A')
                            datePublished = paper.get("PubDate", "N/A")
                            journal = paper.get("FullJournalName", "N/A")

                            lines.append(f"## {title}")
                            lines.append(f"**Date Published**: {datePublished}")
                            lines.append(f"**Journal**: {journal}")
                            lines.append(f"**Authors**: {', '.join(authors)}")
                            lines.append("**More**") # button to open floating window
                            lines.append("") 

                        queryBufHandle[:] = lines
                        queryBufHandle.options['modifiable'] = False

                        winWidth = self.nvim.options['columns']
                        winHeight = self.nvim.options['lines']

                        config = {
                            'relative': 'editor',
                            'row': int(winHeight / 4),
                            'col': int(winWidth / 4),
                            'width': int(winWidth / 2),
                            'height': int(winHeight / 2),
                            'border': 'rounded',
                            'anchor': 'NW', 
                            #'style': 'minimal', 
                            'focusable': True, 
                        }
                        self.nvim.command(':set linebreak')
                        self.nvim.command(':set breakindent')
                        queryWinHandle = self.nvim.api.open_win(queryBufHandle, True, config) # Keep this here, putting it within config dosent work
                        self.nvim.api.win_set_option(queryWinHandle, 'wrap', True)

                    self.nvim.async_call(updateUI)

                except Exception as e:
                    err_msg = str(e)
                    self.nvim.async_call(lambda: self.nvim.err_write(f"Error: {err_msg}\n"))

            threading.Thread(target=task, daemon=True).start()
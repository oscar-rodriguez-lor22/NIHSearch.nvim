import pynvim
import threading
from Bio import Entrez

@pynvim.plugin
class NIHSearch(object):
    def __init__(self, nvim):
        self.nvim = nvim
        Entrez.email = "NIHSearch@nvim.com" 

    @pynvim.command('NIHSearch', nargs='1', sync=False)
    def nih_search(self, args):
        query = args[0]
        self.nvim.out_write(f"Searching NIH for: {query}...\n")

        def task():
            try:
                # Search for ID's
                search_handle = Entrez.esearch(db="pubmed", term=query, retmax=10)
                search_result = Entrez.read(search_handle)
                ids = search_result.get("IdList", [])
                search_handle.close()

                if not ids:
                    self.nvim.err_write(f"No results found for '{query}'\n")
                    return

                # Retrieve summaries using ID's
                summary_handle = Entrez.esummary(db="pubmed", id=",".join(ids))
                summaries = Entrez.read(summary_handle)
                summary_handle.close()

                # UI
                def update_ui():

                    self.nvim.command('new')
                    buf = self.nvim.current.buffer
                    buf.options['buftype'] = 'nofile'
                    buf.options['bufhidden'] = 'wipe'
                    buf.options['filetype'] = 'markdown'
                    
                    lines = [ f"# NIH Search Results: {query}", "---", ""]

                    for paper in summaries:

                        title = paper.get('Title', 'No Title')
                        authors = paper.get('AuthorList', 'Unknown')
                        datePublished = paper.get("PubDate", "Unknown")
                        journal = paper.get("FullJournalName", "Unknown")

                        lines.append(f"## {title}")
                        lines.append(f"Date Published: {[datePublished]}, Journal: {[journal]}")
                        lines.append(f"Authors: {authors}")
                        lines.append("**Read Abstract**") # button to open floating window
                        lines.append("") # Spacer

                    buf[:] = lines
                    buf.options['modifiable'] = False
                    
                    self.nvim.command("nnoremap <buffer> q :q<CR>")

                self.nvim.async_call(update_ui)

            except Exception as e:
                err_msg = str(e)
                self.nvim.async_call(lambda: self.nvim.err_write(f"NIH Error: {err_msg}\n"))

        threading.Thread(target=task, daemon=True).start()
        # Mark each "**Read Abstract**" line with a button
        # OnClick loads abstract into a floatin window

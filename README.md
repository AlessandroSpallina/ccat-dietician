# Dietician

[![Awesome plugin](https://custom-icon-badges.demolab.com/static/v1?label=&message=Awesome+plugin&color=000000&style=for-the-badge&logo=cheshire_cat_ai)](https://github.com/cheshire-cat-ai/awesome-plugins)  


This plugin hooks into the `RabbitHole` to prevend multiple ingestions of the same file by using [LangChain Indexing](https://python.langchain.com/docs/modules/data_connection/indexing).

Using this plugin you can relax yourself and put into the RabbitHole all the files you want, the Dietician will only allow new files (o new versions of the same file, by updating only the modified chunks) for you.

If you like this plugin, please show appreciacion by giving a star to the repository!



## Usage

1. Install this plugin
2. Rebuild the cheshire-cat-ai container
3. Start the cheshire-cat-ai and enable the plugin
4. Relax and ingest all the files you want

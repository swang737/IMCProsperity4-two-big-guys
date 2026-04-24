# Two Big Guys | IMC Prosperity4 Repository
This repository outlines the methods used by my team Two Big Guys that allowed us to place **20th globally** for Algorithmic Trading in Phase 1 of the annual trading challenge hosted by IMC.

## The Team
- Sean Wang
- Nathan Wong (Away for Tutorial and Round 1 due to other commitments)

# Tutorial
Since this was my first time competing in an algorithmic trading challenge of this scale, I felt it would be best to familiarise myself with Prosperity repos from previous years. One repo that was a huge amount of help for me us was the [Prosperity3 Frankfurt Hedgehogs repository](https://github.com/TimoDiehm/imc-prosperity-3#round-3-reserve-price). I adapted their idea of developing custom tools for the competition and reverse engineering the submission website for the true internalized fair value.
## Tools
The biggest edge in the initial rounds was the tools that participants had at their disposal. Whilst I did develop these tools alongside AI, it was used only to write up tedious code. In particular, similar to winning participants in previous years we made sure that we were the ones deciding on logic and UI.
### Backtester
The backtester we used was taken from the open-source channel on the discord. It was made by Kevin Fu and you can find it [here](https://github.com/kevin-fu1/imc-prosperity-4-backtester). I modified the backtester slightly to include data of subsequent rounds and upon runnning it, instead of redirecting to his iniial online visualiser it simply opened up the backtester log in my own custom built visualiser.
### Visualiser
This was probably the most important tool of earlier rounds and the one taking the most time to develop. This is because visualising what is actually happening in the order books is crucial to find *hidden alpha*. *Hidden alpha* is the term I colloquially used to call any sources of PnL that was not attainable by optimising or improving an algorithm, but rather by noticing odd behaviour in the order book.

![Our Visualiser](images\visualiser.png)
*Our Visualiser was probably what helped the most for finding hidden alpha*

Quotes were colored brighter if they had more volume and darker if they had less volume. We later realised that the quotes were from several distinct market participants. We named them *Large Makers*, *Small Makers*, *Trader 1s* and *Trader 2s*. We knew that different participant groups could later prove to be important from historical Prosperity repositories.

We had some fair price models that we were able to select. A couple that proved to work quite well for us was Fill MM, and Fish Mid which I will explain later. I also included an option to normalize since that helped us visualise price differences from our 'fair' much better. The skew price will prove to be important later on.

Unlike other visualisers I had seen, I chose to keep the number of symbols quite minimalistic so that anything odd can be spotted much more easily. Furthermore since my teammate (Nathan Wong) had not been involved in the development of the tools, I wanted the visualisers to be as easy to use as possible. Besides the orderbook which was already discussed, the red and green triangles are our strategy's makes. The red and green crosses are our strategy's takes. The orange line that shows up occasionally happens when the order book is empty.

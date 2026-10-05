"""Official archived Binance OHLCV; perpetual mode adds historical marks and funding."""
import argparse,json
from aster.data.binance_public import download

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',default='BTCUSDT');parser.add_argument('--interval',default='1h',choices=['1s','1m','5m','15m','1h','4h','1d'])
    parser.add_argument('--market',choices=['spot','perpetual'],default='spot')
    parser.add_argument('--start',required=True);parser.add_argument('--end',required=True,help='Exclusive UTC cutoff')
    parser.add_argument('--out',required=True)
    args=parser.parse_args();manifest=download(args.symbol,args.interval,args.start,args.end,args.out,args.market)
    print(json.dumps({k:manifest[k] for k in ['source','symbol','market','first_bar','last_bar_end','rows','expected_rows','funding_rows','quality']},indent=2))
if __name__=='__main__':main()

from settings import *
from web3 import Web3
import json
import os
import sys
import settings 
import requests
import warnings
import pymysql
from concurrent.futures import ThreadPoolExecutor
from preprocess_transactions import *
warnings.filterwarnings('ignore')

# Global debug flag
debug = 0

# Connect to Erigon archive node
w3 = Web3(Web3.HTTPProvider(f"""http://{ERIGON_HOST}:{ERIGON_PORT}"""))

# Open Wrapped Ether json file
with open("abis/ERC20.json") as f:
    json_file   = json.loads(f.read())
    wethAddress = json_file['address']
    wethABI     = json_file['abi']

wethContract = w3.eth.contract(address = wethAddress, abi = wethABI)

# Null
nulladdr = "0x0000000000000000000000000000000000000000"

# DeFi Contracts
swap_contract_list = []
event_name_list    = []
for file in os.listdir("abis/token_exchange"):
    with open(f"abis/token_exchange/{file}") as f:
        json_file   = json.loads(f.read())
        address = json_file['address']
        ABI     = json_file['abi']
        event   = json_file['event']
    exec(f"""{file[:-5]}=w3.eth.contract(address=address,abi=ABI)""")
    swap_contract_list.append(file[:-5])
    event_name_list.append(event)

def find_mev_takers(total_transfer, swap_addresses):
    mev_taker_candidates = []
    excluded             = swap_addresses + [nulladdr]
    for transfer in total_transfer:
        if transfer[0] not in excluded:
            mev_taker_candidates.append(transfer[0])
        if transfer[1] not in excluded:
            mev_taker_candidates.append(transfer[1])
    return set(mev_taker_candidates)

def go_next(node, temp_transfer, candidate, idx_list):
    temp = []
    for idx,transfer in enumerate(temp_transfer):
        if transfer[0] == node and idx not in idx_list:
            temp.append((transfer[1], idx))
        if transfer[0] == node and transfer[1] == candidate and idx not in idx_list:
            if debug : print("Last node :", transfer[1])
            return transfer[1], idx
    if temp:
        if debug : print("Next node :", temp[0][0])
        return temp[0][0], temp[0][1]
    
    return None, None

def check_loop_by_address(candidate, total_transfer, swap_addresses):
    temp_transfer = total_transfer.copy()
    loops_address, loops_token, loops_amount = [], [], []
    loop_address, loop_token, loop_amount = [], [], []

    node = candidate
    idx_list = []
    if debug : print("Candidate :", candidate)
    additional_profit = []
    while True:
        if debug : print("Current node :", node)
        loop_address.append(node)
        node, idx = go_next(node, temp_transfer, candidate, idx_list)
        idx_list.append(idx)
        
        if node is None:
            if len(loop_address) > 1:
                # Go back
                node = loop_address[-2]
                del loop_address[-2:]
                temp_transfer[idx_list[-2]] = [None,None,None,None]
                del idx_list[-2:]
                continue
            else:
                # Terminate
                if len(loop_address) <= 1 and node is None:
                    break        
            
        # Loop Found
        if len(loop_address) > 1 and node == candidate:
            no_loop = False
            
            loop_amount, loop_token = [], []
            
            for k in idx_list:
                loop_token.append(temp_transfer[k][3])
                loop_amount.append(temp_transfer[k][2])   
            
            # same token, same amount
            same_amount_idx = []
            for idx in range(len(loop_token)-1):
                if loop_token[idx] == loop_token[idx+1]:
                    if loop_amount[idx] == loop_amount[idx+1]:
                        same_amount_idx.append(idx+1)
            for k in sorted(same_amount_idx, reverse=True):
                del loop_address[k]
                del loop_token[k]
                del loop_amount[k]
            
            # no swap addr
            not_swap_addr = []
            for addr_idx,addr in enumerate(loop_address[1:]):
                if addr not in swap_addresses:
                    not_swap_addr.append([addr_idx,addr])                 
            
            if len(not_swap_addr)>=2:
                no_loop = True

            if len(set(loop_token)) == 1:
                no_loop = True
            
            if len(not_swap_addr) == 1:
                if len(loop_address) == 2:
                    no_loop = True
                else:
                    addr_idx = not_swap_addr[0][0]
                    if loop_token[addr_idx] != loop_token[addr_idx+1]:
                        no_loop = True
                    if loop_amount[addr_idx] < loop_amount[addr_idx+1]:
                        no_loop = True
                    if not no_loop:
                        additional_profit = [loop_token[addr_idx], loop_amount[addr_idx]-loop_amount[addr_idx+1]]

            if no_loop:
                loop_address = []
                node = candidate
                for k in sorted(idx_list, reverse=True):       
                    del temp_transfer[k]
                idx_list = []
                continue
            
            if debug: print("Loop found :", loop_address, loop_token, loop_amount)
            
            loops_address.append(loop_address)
            loop_address = []
            node = candidate
            
            loops_token.append(loop_token)
            loops_amount.append(loop_amount)
            
            for k in sorted(idx_list, reverse=True):       
                del temp_transfer[k]
            idx_list = []
    
    if loops_address:
        # simple swap
        if len(loops_address) == 1 and loops_token[0][0] != loops_token[0][-1]:
            return None, None, None, None
        return loops_address, loops_token, loops_amount, additional_profit
    return None, None, None, None

def check_loops(tx, total_transfer = None):
    receipt = w3.eth.getTransactionReceipt(tx)
    if total_transfer is None:
        total_transfer = get_total_transfer(tx, receipt)
    if not total_transfer:
        return None, None, None, None, None
    
    # EVENTS
    swap_addresses, platforms = [], []
    
    # Synapse
    temp = synapse.events.TokenSwap().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('synapse')
        
    # stablePlaza
    temp = stablePlaza.events.Swap().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('stablePlaza')
        
    # astETH
    temp = astETH.events.Burn().processReceipt(receipt)
    if temp:       
        swap_addresses += [swap['address'].lower() for swap in temp]
        stETH_mint, astETH_burnt = False, False
        for idx, transfer in enumerate(total_transfer):
            if transfer[0] == "0x1982b2f5814301d4e9a8b0201555376e62f82428":
                stETH_mint = True
            if transfer[1] == nulladdr and transfer[3] == "0x1982b2F5814301d4e9a8b0201555376e62F82428":
                astETH_idx = idx
                astETH_burnt = True
        if stETH_mint and astETH_burnt:
            total_transfer[astETH_idx][1] = "0x1982b2f5814301d4e9a8b0201555376e62f82428"
        platforms.append('astETH')
        
    # kyberDMM
    temp = kyberDMM.events.Swap().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('kyberDMM')
        
    # clipper
    temp = clipper.events.Swapped().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('clipper')
        
    # eclipseum
    temp = eclipseum.events.LogBuyDai().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('eclipseum')
        
    # zeroxV3
    temp = zeroxV3.events.Fill().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        for event in temp:
            maker = event['args']['makerAddress'].lower()
            swap_addresses.append(maker)
        platforms.append('zeroxV3')
        
    # metronome
    temp = metronome.events.ConvertMetToEth().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('metronome')
    
    # helixswap
    temp = helixswap.events.Swap().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('helixswap')
        
    # liquity
    temp = liquity.events.Liquidation().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('liquity')
        
    # FPIcontroller
    temp = FPIcontroller.events.FPIRedeemed().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('FPIcontroller')
        
    # uniswapV2
    temp = uniswapV2.events.Swap().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        for idx, transfer in enumerate(total_transfer):
            if transfer[3] == receipt['to']:
                total_transfer[idx] = [0,1,0,0]
        platforms.append('uniswapV2')
        
    # uniswapV3
    temp = uniswapV3.events.Swap().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('uniswapV3')
        
    # comet
    temp = comet.events.BuyCollateral().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('comet')
        
    # balancerPool
    temp = balancerPool.events.LOG_SWAP().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('balancerPool')
        
    # balancerVault
    temp = balancerVault.events.Swap().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('balancerVault')
        
    # defiPlaza
    temp = defiPlaza.events.Swapped().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('defiPlaza')
        
    # curve
    temp = curve.events.TokenExchange().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('curve')
        
    # crv3pool - AddLiquidity
    temp = crv3pool.events.AddLiquidity().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        for idx, transfer in enumerate(total_transfer):
            if transfer[0] == nulladdr and transfer[3] == "0x6c3F90f043a72FA612cbac8115EE7e52BDe6E490":
                total_transfer[idx][0] = "0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7"
                break
        platforms.append('crv3pool')
        
    # crv3pool - RemoveLiquidity
    temp = crv3pool.events.RemoveLiquidity().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        for idx, transfer in enumerate(total_transfer):
            if transfer[1] == nulladdr and transfer[3] == "0x6c3F90f043a72FA612cbac8115EE7e52BDe6E490":
                total_transfer[idx][1] = "0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7"
                break
        platforms.append('crv3pool')
        
    # bancorConverter
    temp = bancorConverter.events.Conversion().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('bancorConverter')
        
    # ren - LogMint
    temp = ren.events.LogMint().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('ren')
        
    # ren - LogBurn
    temp = ren.events.LogBurn().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('ren')
        
    # bancorSwaps
    temp = bancorSwaps.events.Conversion().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('bancorSwaps')
        
    # ironbank
    temp = ironbank.events.Mint().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('ironbank')
        
    # bancorNetwork
    temp = bancorNetwork.events.TokensTraded().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('bancorNetwork')
    
    # curveSwap
    temp = curveSwap.events.TokenExchange().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('curveSwap')
        
    # curve2
    temp = curve2.events.TokenExchange().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('curve2')
        
    # aaveLiquidations
    temp = aaveLiquidations.events.LiquidationCall().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('aaveLiquidations')
        
    # Aave Liquidations
    if "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9" in swap_addresses:            
        liq = aaveLiquidations.events.LiquidationCall().processReceipt(receipt)
        if liq:
            liq = liq[0]['args']
            collateralAsset = liq['collateralAsset']
            debtAsset = liq['debtAsset']
            debtToCover = liq['debtToCover']
            liquidatedCollateralAmount = liq['liquidatedCollateralAmount']
            liquidator = liq['liquidator'].lower()

            for transfer in total_transfer:
                if transfer[1] == liquidator and transfer[2]//10**9 == liquidatedCollateralAmount//10**9 and transfer[3] == collateralAsset:
                    t2 = transfer[0]
                if transfer[0] == liquidator and transfer[2]//10**9 == debtToCover//10**9 and transfer[3] == debtAsset:
                    t1 = transfer[1]
            try:
                total_transfer.append([t1, t2, 0, 1])
                swap_addresses += [t1, t2]
            except:
                pass
        
    # mstable
    temp = mstable.events.Swapped().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        
        for idx, transfer in enumerate(total_transfer):
            if transfer[1] == temp[0]['args']['recipient'].lower() and abs(transfer[2] - temp[0]['args']['outputAmount']) <= temp[0]['args']['outputAmount']/10**12 and transfer[3] == temp[0]['args']['output']:
                total_transfer.append([temp[0]['address'].lower(), transfer[0],1,"x"])
                swap_addresses.append(transfer[0])
                break
        platforms.append('mstable')
        
    # mstable
    temp = mstable.events.Redeemed().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        
        args = temp[0]['args']
        for idx, transfer in enumerate(total_transfer):
            if transfer[1] == args['recipient'].lower() and transfer[2] - args['outputQuantity'] == 0:
                r = transfer[0]
        
        for idx, transfer in enumerate(total_transfer):
            if transfer[0] == args['redeemer'].lower() and transfer[1] == nulladdr and transfer[2] - args['mAssetQuantity'] == 0:
                total_transfer[idx][1] = r
                break
        swap_addresses.append(r)
        platforms.append('mstable')
        
    
    # olympusPro
    temp = olympusPro.events.Bond().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('olympusPro')
        
    # sudoswap
    temp = sudoswap.events.SwapNFTInPair().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('sudoswap')
        
    # sudoswap
    temp = sudoswap.events.SwapNFTOutPair().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('sudoswap')
        
    # uniswapV1
    temp = uniswapV1.events.TokenPurchase().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('uniswapV1')
        
    # nativeorder - LimitOrderFilled
    temp = nativeorder.events.LimitOrderFilled().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        args = nativeorder.events.LimitOrderFilled().processReceipt(receipt)[0]['args']
        swap_addresses.append(args['maker'].lower())
        platforms.append('nativeorder')
        
    # nativeorder - RfqOrderFilled
    temp = nativeorder.events.RfqOrderFilled().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        args = nativeorder.events.RfqOrderFilled().processReceipt(receipt)[0]['args']
        swap_addresses.append(args['maker'].lower())
        platforms.append('nativeorder')
        
    # dodoswap2 - BuyBaseToken
    temp = dodoswap2.events.BuyBaseToken().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('dodoswap2')
        
    # dodoswap2 - SellBaseToken
    temp = dodoswap2.events.SellBaseToken().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('dodoswap2')
        
    # mooniSwap
    temp = mooniSwap.events.Swapped().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('mooniSwap')
        
    # kyber
    temp = kyber.events.KyberTrade().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('kyber')
        
    # mooniSwap_2
    temp = mooniSwap_2.events.Swapped().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('mooniSwap_2')
        
    # uniswapV1_2
    temp = uniswapV1_2.events.EthPurchase().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('uniswapV1_2')
        
    # muffinhub
    temp = muffinhub.events.Swap().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('muffinhub')
        
    # curveStable
    temp = curveStable.events.TokenExchangeUnderlying().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('curveStable')
        
    # fixedPricePSM
    temp = fixedPricePSM.events.Redeem().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('fixedPricePSM')
        
    # angleStable
    temp = angleStable.events.BurntStablecoins().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('angleStable')
        
    # yearnBuyBack
    temp = yearnBuyBack.events.Buyback().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('yearnBuyBack')
        
    # dodoswap
    temp = dodoswap.events.DODOSwap().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('dodoswap')
        
    # curve3
    temp = curve3.events.Trade().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('curve3')
        
    # nfti
    temp = nfti.events.SetTokenRedeemed().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('nfti')
        
    # rariCapital
    temp = rariCapital.events.LiquidateBorrow().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        args = temp[0]['args']
        for idx, transfer in enumerate(total_transfer):
            if transfer[0] == args['liquidator'].lower() and abs(transfer[2] - args['repayAmount']) <=args['repayAmount']/10**9:
                total_transfer[idx][1] = args['borrower'].lower()
                break
        swap_addresses.append(args['borrower'].lower())
        
        platforms.append('rariCapital')
        
    
    # powerIndex - LOG_JOIN
    temp = powerIndex.events.LOG_JOIN().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('powerIndex')
        
    # powerIndex - LOG_EXIT
    temp = powerIndex.events.LOG_EXIT().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('powerIndex')
        
    # dsspsm - BuyGem
    temp = dsspsm.events.BuyGem().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('dsspsm')
        
    # dsspsm - SellGem
    temp = dsspsm.events.SellGem().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('dsspsm')
        
    # bpool 
    temp = bpool.events.LOG_SWAP().processReceipt(receipt)
    if temp: 
        swap_addresses += [swap['address'].lower() for swap in temp]
        platforms.append('bpool')
    
    
    
    # Function call
    r = requests.post(f"http://{ERIGON_HOST}:{ERIGON_PORT}/",json =  {"method":"trace_transaction","params":[tx],"id":1,"jsonrpc":"2.0"})
    traces = json.loads(r.text)['result']

    for trace in traces:
        try:
            if trace['action']['to'] == "0x5d0f47b32fdd343bfa74ce221808e2abe4a53827":
                if vyperStable.decode_function_input(trace['action']['input'])[0].fn_name == "exchange_underlying":
                    swap_addresses.append("0x5d0f47b32fdd343bfa74ce221808e2abe4a53827")
                    platforms.append('vyperStable')
                    
            if trace['action']['to'] == "0xfdcc959b0aa82e288e4154cb1c770c6c4e958a91":
                if phononRedeemer.decode_function_input(trace['action']['input'])[0].fn_name == "redeem":
                    swap_addresses.append("0xfdcc959b0aa82e288e4154cb1c770c6c4e958a91")
                    platforms.append('phononRedeemer')
                    
            if trace['action']['to'] == "0xd9a4cb9dc9296e111c66dfacab8be034ee2e1c2c":
                if adex.decode_function_input(trace['action']['input'])[0].fn_name == "leave":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == nulladdr and transfer[3] == "0xd9A4cB9dc9296e111c66dFACAb8Be034EE2E1c2C":
                            break
                    total_transfer[idx][1] = "0xd9a4cb9dc9296e111c66dfacab8be034ee2e1c2c"
                    swap_addresses.append("0xd9a4cb9dc9296e111c66dfacab8be034ee2e1c2c")
                    platforms.append('adex')
                    
#             if trace['action']['to'] == "0x3ed04ceff4c91872f19b1da35740c0be9ca21558":
#                 data = synthetix.decode_function_input(trace['action']['input'])
#                 if data[0].fn_name == "exchangeAtomically":
#                     for idx,transfer in enumerate(total_transfer):
#                         if transfer[0] == data[1]['from'].lower() and transfer[2] - data[1]['sourceAmount'] == 0:
#                             total_transfer[idx][1] = "synthetix"
#                         if transfer[1] == data[1]['destinationAddress'].lower() and transfer[2] - data[1]['minAmount'] == 0:
#                             total_transfer[idx][0] = "synthetix"
#                     swap_addresses.append("synthetix")

            if trace['action']['to'] == "0xedb171c18ce90b633db442f2a6f72874093b49ef":
                data = ampleforth.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "depositFor":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[0] == nulladdr and transfer[1] == data[1]['to'].lower():
                            total_transfer[idx][0] = "0xedb171c18ce90b633db442f2a6f72874093b49ef"
                            break
                    swap_addresses.append("0xedb171c18ce90b633db442f2a6f72874093b49ef")
                    platforms.append('ampleforth')
                    
                if data[0].fn_name == "burnAllTo":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == nulladdr and transfer[3] == "0xEDB171C18cE90B633DB442f2A6F72874093b49Ef":
                            total_transfer[idx][1] = "0xedb171c18ce90b633db442f2a6f72874093b49ef"
                            break
                    swap_addresses.append("0xedb171c18ce90b633db442f2a6f72874093b49ef")
                    platforms.append('ampleforth')
                    
                if data[0].fn_name == "deposit":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[0] == nulladdr and transfer[3] == "0xEDB171C18cE90B633DB442f2A6F72874093b49Ef":
                            total_transfer[idx][0] = "0xedb171c18ce90b633db442f2a6f72874093b49ef"
                            break
                    swap_addresses.append("0xedb171c18ce90b633db442f2a6f72874093b49ef")
                    platforms.append('ampleforth')
                    
            if trace['action']['to'] == "0x8798249c2e607446efb7ad49ec89dd1865ff4272":
                data = xsushi.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "leave":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == nulladdr and transfer[3] == "0x8798249c2E607446EfB7Ad49eC89dD1865Ff4272":
                            total_transfer[idx][1] = "0x8798249c2e607446efb7ad49ec89dd1865ff4272"
                            break
                    swap_addresses.append("0x8798249c2e607446efb7ad49ec89dd1865ff4272")
                    platforms.append('xsushi')
                    
                if data[0].fn_name == "enter":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[0] == nulladdr and transfer[3] == "0x8798249c2E607446EfB7Ad49eC89dD1865Ff4272":
                            total_transfer[idx][0] = "0x8798249c2e607446efb7ad49ec89dd1865ff4272"
                            break
                    swap_addresses.append("0x8798249c2e607446efb7ad49ec89dd1865ff4272")
                    platforms.append('xsushi')
                    
            if trace['action']['to'] == "0x184f3fad8618a6f458c16bae63f70c426fe784b3":
                data = olympus.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "bridgeBack":
                    swap_addresses.append("0x184f3fad8618a6f458c16bae63f70c426fe784b3")
                    platforms.append('olympus')
                    
            if trace['action']['to'] == "0xb4a81261b16b92af0b9f7c4a83f1e885132d81e4":
                data = xSHIB.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "leave":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == nulladdr and transfer[3] == "0xB4a81261b16b92af0B9F7C4a83f1E885132D81e4":
                            total_transfer[idx][1] = "0xb4a81261b16b92af0b9f7c4a83f1e885132d81e4"
                            break
                    swap_addresses.append("0xb4a81261b16b92af0b9f7c4a83f1e885132d81e4")
                    platforms.append('xSHIB')
                    
                if data[0].fn_name == "enter":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[0] == nulladdr and transfer[3] == "0xB4a81261b16b92af0B9F7C4a83f1E885132D81e4":
                            total_transfer[idx][0] = "0xb4a81261b16b92af0b9f7c4a83f1e885132d81e4"
                            break
                    swap_addresses.append("0xb4a81261b16b92af0b9f7c4a83f1e885132d81e4")
                    platforms.append('xSHIB')
                    
            if trace['action']['to'] == "0xb63cac384247597756545b500253ff8e607a8020":
                data = olympusStaking.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "unstake":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == nulladdr and transfer[3] == "0x0ab87046fBb341D058F17CBC4c1133F25a20a52f":
                            total_transfer[idx][1] = "0xb63cac384247597756545b500253ff8e607a8020"
                            break
                    swap_addresses.append("0xb63cac384247597756545b500253ff8e607a8020")
                    platforms.append('olympusStaking')
                    
                if data[0].fn_name == "stake":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == data[1]['_to'].lower() and transfer[3] == "0x0ab87046fBb341D058F17CBC4c1133F25a20a52f":
                            total_transfer[idx][0] = "0xb63cac384247597756545b500253ff8e607a8020"
                            break
                    swap_addresses.append("0xb63cac384247597756545b500253ff8e607a8020")
                    platforms.append('olympusStaking')
                    
            if trace['action']['to'] == "0x9d409a0a012cfba9b15f6d4b36ac57a46966ab9a":
                data = yvBoost.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "deposit":
                    for idx,transfer in enumerate(total_transfer):
                        if transfer[0] == nulladdr and transfer[1] == data[1]['recipient'].lower():
                            total_transfer[idx][0] = "0x9d409a0a012cfba9b15f6d4b36ac57a46966ab9a"
                            break
                    swap_addresses.append("0x9d409a0a012cfba9b15f6d4b36ac57a46966ab9a")
                    platforms.append('yvBoost')
                    
            if trace['action']['to'] == "0x1fcc3e6f76f7a96cd2b9d09f1d3c041ca1403c57":
                data = nativeorder.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "fillRfqOrder":
                    swap_addresses.append(data[1]['order'][4].lower())
                    platforms.append('nativeorder')

            if trace['action']['to'] == "0xc6845a5c768bf8d7681249f8927877efda425baf":
                data = aaveLending.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "finalizeTransfer":
                    swap_addresses.append(data[1]['from'].lower())                    
                    platforms.append('aaveLending')
                    
            if trace['action']['to'] == "0xbe1b2dfb095c59da22df63df4bc8f92e11a2f620":
                data = omi.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "mint":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == nulladdr and transfer[0] == data[1]['to'].lower() and transfer[3] == "0x04969cD041C0cafB6AC462Bd65B536A5bDB3A670":
                            total_transfer[idx][1] = "omi"
                        if transfer[0] == nulladdr and transfer[1] == data[1]['to'].lower() and transfer[3] == "0xeD35af169aF46a02eE13b9d79Eb57d6D68C1749e":
                            total_transfer[idx][0] = "omi"
                    swap_addresses.append("omi")
                    platforms.append('omi')
                    
            if trace['action']['to'] == "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0":
                data = wstETH.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "wrap":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[0] == nulladdr and transfer[3] == "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0":
                            total_transfer[idx][0] = "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0"
                            break
                    swap_addresses.append("0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0")
                    platforms.append('wstETH')
                    
                if data[0].fn_name == "unwrap":
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == nulladdr and transfer[3] == "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0":
                            total_transfer[idx][1] = "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0"
                            break
                    swap_addresses.append("0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0")
                    platforms.append('wstETH')
                    
            if trace['action']['to'] == "0x119c71d3bbac22029622cbaec24854d3d32d2828":
                data = oneinchLim.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "fillOrder":
                    swap_addresses.append(data[1]['order'][3].lower())
                    platforms.append('oneinchLim')
                    
            if trace['action']['to'] == "0x5d4c724bfe3a228ff0e29125ac1571fe093700a4":
                data = synthetixMulti.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "burn":
                    swap_addresses.append("synthetixMulti")
                    platforms.append('synthetixMulti')
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == nulladdr and transfer[2] - data[1]['amount'] == 0:
                            total_transfer[idx][1] = "synthetixMulti"
                        if transfer[0] == nulladdr and transfer[1] == data[1]['account'].lower() and transfer[3] == "0x57Ab1ec28D129707052df4dF418D58a2D46d5f51":
                            total_transfer[idx][0] = "synthetixMulti"
                            
            if trace['action']['to'] == "0xe4fe6a45f354e845f954cddee6084603cedb9410":
                data = sashimiswap.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "swapExactTokensForTokens":
                    swap_addresses.append("0xe4fe6a45f354e845f954cddee6084603cedb9410")
                    platforms.append('sashimiswap')
                    
            if trace['action']['to'] == "0x4b520c812e8430659fc9f12f6d0c39026c83588d":
                data = decentralgames.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "goLight":
                    swap_addresses.append("0x4b520c812e8430659fc9f12f6d0c39026c83588d")
                    platforms.append('decentralgames')
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[0] == nulladdr and transfer[2]/10**3 - data[1]['_classicAmountToDeposit'] == 0:
                            total_transfer[idx][0] = "0x4b520c812e8430659fc9f12f6d0c39026c83588d"
                if data[0].fn_name == "goClassic":
                    swap_addresses.append("0x4b520c812e8430659fc9f12f6d0c39026c83588d")
                    platforms.append('decentralgames')
                    for idx, transfer in enumerate(total_transfer):
                        if transfer[1] == nulladdr and transfer[2]/10**3 - data[1]['_classicAmountToReceive'] == 0:
                            total_transfer[idx][1] = "0x4b520c812e8430659fc9f12f6d0c39026c83588d"
                            
            if trace['action']['to'] == "0xc586bef4a0992c495cf22e1aeee4e446cecdee0e":
                data = oneSplit.decode_function_input(trace['action']['input'])
                if data[0].fn_name == "swap":
                    swap_addresses.append("0xc586bef4a0992c495cf22e1aeee4e446cecdee0e")
                    platforms.append('oneSplit')
        except:
            pass
    
    # Events
    
    # Bancor 

    if "0xeef417e1d5cc832e619ae18d2f140de2999dd4fb" in swap_addresses:
        for idx, transfer in enumerate(total_transfer):
            if transfer[1] == "0xeef417e1d5cc832e619ae18d2f140de2999dd4fb":
                sender = transfer[0]
                total_transfer[idx] = [0,1,0,0]
            if transfer[0] == "0xeef417e1d5cc832e619ae18d2f140de2999dd4fb":
                try:
                    total_transfer[idx][0] = sender
                except:
                    pass
                
        swap_addresses.append("0x649765821d9f64198c905ec0b2b037a4a52bc373")
   
    if "0x2f9ec37d6ccfff1cab21733bdadede11c823ccb0" in swap_addresses:
        for idx, transfer in enumerate(total_transfer):
            if transfer[1] == "0x2f9ec37d6ccfff1cab21733bdadede11c823ccb0":
                sender = transfer[0]
                total_transfer[idx] = [0,1,0,0]
            if transfer[0] == "0x2f9ec37d6ccfff1cab21733bdadede11c823ccb0":
                try:
                    total_transfer[idx][0] = sender
                except:
                    pass    
        
    # Angle Stable Burnt 
    if "0x5addc89785d75c86ab939e9e15bfbbb7fc086a87" in swap_addresses:
        stable_mint, stable_burnt = False, False
        for idx, transfer in enumerate(total_transfer):
            if transfer[0] == "0xe9f183fc656656f1f17af1f2b0df79b8ff9ad8ed":
                stable_mint = True
            if transfer[1] == nulladdr:
                stable_idx = idx
                stable_burnt = True
        if stable_mint and stable_burnt:
            total_transfer[stable_idx][1] = "0xe9f183fc656656f1f17af1f2b0df79b8ff9ad8ed"
            swap_addresses.append("0xe9f183fc656656f1f17af1f2b0df79b8ff9ad8ed")
        
        
    # yearn stable
    if "0x6903223578806940bd3ff0c51f87aa43968424c8" in swap_addresses:
        total_transfer.append(["0xfeb4acf3df3cdea7399794d0869ef76a6efaff52","0x6903223578806940bd3ff0c51f87aa43968424c8",0,1])
        swap_addresses += ["0xfeb4acf3df3cdea7399794d0869ef76a6efaff52","0x6903223578806940bd3ff0c51f87aa43968424c8"]
        
    # OHM to DAI
    if "0x22ae99d07584a2ae1af748de573c83f1b9cdb4c0" in swap_addresses:
        swap_addresses.append("0xba42be149e5260eba4b82418a6306f55d532ea47")
        
    if "0xd8ef3cace8b4907117a45b0b125c68560532f94d" in swap_addresses:
        redeemed_event = nfti.events.SetTokenRedeemed().processReceipt(receipt)[0]['args']
        setToken = redeemed_event['_setToken']
        redeemer = redeemed_event['_redeemer']
        
        is_first = True
        for idx, transfer in enumerate(total_transfer):
            if transfer[1] == nulladdr and transfer[3] == setToken:
                burnt_nfti = transfer[2]
                continue
                
            if transfer[0] == setToken.lower() and transfer[1] == redeemer.lower():
                nfti_amount = burnt_nfti if is_first else 0
                total_transfer.append([transfer[1], transfer[0], nfti_amount, setToken])
                is_first = False
        swap_addresses.append(setToken.lower())
        platforms.append('nfti')
    
    if "0x89b78cfa322f6c5de0abceecab66aee45393cc5a" in swap_addresses:
        buyGem = dsspsm.events.BuyGem().processReceipt(receipt)
        sellGem = dsspsm.events.SellGem().processReceipt(receipt)
        if buyGem:
            for idx, transfer in enumerate(total_transfer):
                if transfer[0] == "0x89b78cfa322f6c5de0abceecab66aee45393cc5a" and transfer[1] == nulladdr:
                    total_transfer[idx][1] = "0x0a59649758aa4d66e25f08dd01271e891fe52199"
                    swap_addresses.append("0x0a59649758aa4d66e25f08dd01271e891fe52199")
                    break
        if sellGem:
            for idx, transfer in enumerate(total_transfer):
                if transfer[0] == nulladdr and transfer[1] == sellGem[0]['args']['owner'].lower():
                    total_transfer[idx][0] = "0x0a59649758aa4d66e25f08dd01271e891fe52199"
                    swap_addresses.append("0x0a59649758aa4d66e25f08dd01271e891fe52199")
                    break    

    # iron bank
    if ironbank.events.Mint().processReceipt(receipt):
        args = ironbank.events.Mint().processReceipt(receipt)[0]['args']
        swap_addresses.append(args['minter'].lower())
        for idx, transfer in enumerate(total_transfer):
            if transfer[0] == nulladdr and transfer[2] - args['mintTokens'] == 0:
                total_transfer[idx][0] = args['minter'].lower()
                break

    mev_taker_candidates  = find_mev_takers(total_transfer, swap_addresses)
    
    loops_address_all = []
    loops_token_all = []
    loops_amount_all = []
    additional_profit_all = {}
    for candidate in mev_taker_candidates:
        loops_address, loops_token, loops_amount, additional_profit = check_loop_by_address(candidate, total_transfer, swap_addresses)
        if loops_address:
            loops_address_all += loops_address
            loops_token_all += loops_token
            loops_amount_all += loops_amount
        try:
            additional_profit_all[candidate] = additional_profit
        except:
            pass
            
    return loops_address_all, loops_token_all, loops_amount_all, additional_profit_all, platforms

def cal_profit(nodes, tokens, amounts):
    profit = {}
    for i in range(len(nodes)):
        if nodes[i][0] not in profit.keys():
            if tokens[i][0] == tokens[i][-1]:
                profit[nodes[i][0]] = {tokens[i][0]: amounts[i][-1]-amounts[i][0]}
            else:
                profit[nodes[i][0]] = {tokens[i][0]: -amounts[i][0], tokens[i][-1]: amounts[i][-1]}
        else:
            try:
                profit[nodes[i][0]][tokens[i][0]] -= amounts[i][0]
            except:
                profit[nodes[i][0]][tokens[i][0]] = -amounts[i][0]
            try:
                profit[nodes[i][0]][tokens[i][-1]] += amounts[i][-1]
            except:
                profit[nodes[i][0]][tokens[i][-1]] = amounts[i][-1]      
    return profit

def find_arbitrage(tx, total_transfer = None, debug_flag=0):
    global debug
    debug = debug_flag
    nodes, tokens, amounts, additional_profit_all, platforms = check_loops(tx, total_transfer)

    if not nodes:
        return None, None, None
    
    profits = cal_profit(nodes, tokens, amounts)

    mev_profits = {}
    for address, profit in profits.items():
        skip = False
        for token,val in profit.items():
            if val < 0:
                if check_if_trivial(token, -val, tokens, amounts):
                    profits[address][token] = 0
                else:
                    skip = True
        if additional_profit_all:    
            try:
                profit[additional_profit_all[address][0]] += additional_profit_all[address][1]
            except:
                try:
                    profit[additional_profit_all[address][0]] = additional_profit_all[address][1]
                except:
                    pass
        if skip or sum(profit.values())<=0:
            continue    
        mev_profits[address] = profit
    if mev_profits:
        print(f"Found MEV ! {tx}")
        return mev_profits, list(mev_profits.keys()), platforms
    return None, None, None

def check_if_trivial(token, val, tokens, amounts):
    is_trivial = False
    tokens_flattened = [item for sublist in tokens for item in sublist]
    amounts_flattened = [item for sublist in amounts for item in sublist]
    for idx, t1 in enumerate(tokens_flattened):
        if t1 == token:
            if amounts_flattened[idx] > val*500:
                is_trivial = True
                break
    return is_trivial

def process_transaction(data, blockNum):
    tx = data[0]
    total_transfer = None
    
    _, mev_takers, platforms = find_arbitrage(tx, total_transfer)
    if not mev_takers:
        return None

    return (blockNum, tx, mev_takers[0], json.dumps(platforms))


def update_mev_db(start, end, table):
    batch = 1
    with ThreadPoolExecutor(max_workers=5) as executor:
        for blockNum in range(start, end, batch):
            if blockNum % 10 == 0: continue
                        
            transactions = [(tx.hex(), None, blockNum) for tx in w3.eth.getBlock(blockNum)['transactions']]
                
            process_transaction_args = [(data, data[2]) for data in transactions]
            
            rows = list(filter(None, executor.map(lambda args: process_transaction(*args), process_transaction_args)))
            mycursor.executemany(f"""INSERT IGNORE INTO {table} (block, tx_hash, taker_address, platforms) VALUES (%s,%s,%s,%s)""", rows)

            if blockNum % 100 == 99 or blockNum == end-1:
                print(blockNum)
                mydb.commit()
            

if __name__ == "__main__":
    table = "labeled_arbitrages"
    start = int(sys.argv[1])
    end   = int(sys.argv[2])

    # Connect to MySQL server
    mydb = pymysql.connect(
    host=DB_HOST,
    user=DB_USER,
    password=DB_PASSWORD,
    database="Ethereum")

    mycursor = mydb.cursor()

    # DDL
    update_mev_db(start, end, table)
